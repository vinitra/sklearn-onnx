"""
Helpers to test runtimes.
"""
import os
import glob
import pickle
import numpy
import warnings
from numpy.testing import assert_array_almost_equal, assert_array_equal
from .utils_backend import load_data_and_model, extract_options, ExpectedAssertionError, OnnxRuntimeAssertionError, compare_outputs


def compare_runtime(test, decimal=5, options=None, verbose=False, context=None):
    """
    The function compares the expected output (computed with
    the model before being converted to ONNX) and the ONNX output
    produced with module *onnxruntime*.
    
    :param test: dictionary with the following keys:
        - *onnx*: onnx model (filename or object)
        - *expected*: expected output (filename pkl or object)
        - *data*: input data (filename pkl or object)
    :param decimal: precision of the comparison
    :param options: comparison options
    :param context: specifies custom operators
    :param verbose: in case of error, the function may print
        more information on the standard output
    :return: tuple (outut, lambda function to run the predictions)
    
    The function does not return anything but raises an error
    if the comparison failed.
    """
    lambda_onnx = None
    if context is None:
        context = {}
    load = load_data_and_model(test, **context)

    onx = test['onnx']
    if options is None:
        if isinstance(onx, str):
            options = extract_options(onx)
        else:
            options = {}
    elif options is None:
        options = {}
    elif not isinstance(options, dict):
        raise TypeError("options must be a dictionary.")

    try:
        import onnxruntime
    except ImportError as e:
        warnings.warn("Unable to import onnxruntime.")
        return None

    try:
        sess = onnxruntime.InferenceSession(onx)
    except ExpectedAssertionError as expe:
        raise expe
    except Exception as e:
        if "CannotLoad" in options:
            raise ExpectedAssertionError("Unable to load onnx '{0}' due to\n{1}".format(onx, e))
        else:
            if verbose:
                import onnx
                model = onnx.load(onx)
                smodel = "\nJSON ONNX\n" + str(model)
            else:
                smodel = ""
            raise OnnxRuntimeAssertionError("Unable to load onnx '{0}'\nONNX\n{1}".format(onx, smodel))
    
    input = load["data"]
    if isinstance(input, dict):
        inputs = input
    elif isinstance(input, (list, numpy.ndarray)):
        inp = sess.get_inputs()
        if len(inp) == len(input):
            inputs = {i.name: v for i, v in zip(inp, input)}
        elif len(inp) == 1:
            inputs = {inp[0].name: input}
        elif isinstance(input, numpy.ndarray):
            shape = sum(i.shape[1] if len(i.shape) == 2 else i.shape[0] for i in inp)
            if shape == input.shape[1]:
                inputs = {n.name: input[:, i] for i, n in enumerate(inp)}
            else:
                raise OnnxRuntimeAssertionError("Wrong number of inputs onnx {0} != original shape {1}, onnx='{2}'".format(len(inp), input.shape, onnx))
        elif isinstance(input, list):
            try:
                array_input = numpy.array(input)
            except Exception as e:
                raise OnnxRuntimeAssertionError("Wrong number of inputs onnx {0} != original {1}, onnx='{2}'".format(len(inp), len(input), onnx))
            shape = sum(i.shape[1] for i in inp)
            if shape == array_input.shape[1]:
                inputs = {n.name: _create_column([row[i] for row in input], n.type) for i, n in enumerate(inp)}
            else:
                raise OnnxRuntimeAssertionError("Wrong number of inputs onnx {0} != original shape {1}, onnx='{2}'*".format(len(inp), array_input.shape, onnx))
        else:
            raise OnnxRuntimeAssertionError("Wrong number of inputs onnx {0} != original {1}, onnx='{2}'".format(len(inp), len(input), onnx))
    else:
        raise OnnxRuntimeAssertionError("Dict or list is expected, not {0}".format(type(input)))
        
    for k in inputs:
        if isinstance(inputs[k], list):
            inputs[k] = numpy.array(inputs[k])
    
    OneOff = options.pop('OneOff', False)
    options.pop('SklCol', False)  # unused here but in dump_data_and_model
    if OneOff:
        if len(inputs) == 1:
            name, values = list(inputs.items())[0]
            res = []
            for input in values:
                try:
                    one = sess.run(None, {name: input})
                    if lambda_onnx is None:
                        lambda_onnx = lambda: sess.run(None, {name: input})
                except ExpectedAssertionError as expe:
                    raise expe
                except Exception as e:
                    raise OnnxRuntimeAssertionError("Unable to run onnx '{0}' due to {1}".format(onnx, e))
                res.append(one)
            output = _post_process_output(res)
        else:
            def to_array(vv):
                if isinstance(vv, (numpy.ndarray, numpy.int64, numpy.float32)):
                    return numpy.array([vv])
                else:
                    return numpy.array([vv], dtype=numpy.float32)
            t = list(inputs.items())[0]
            res = []
            for i in range(0, len(t[1])):                
                iii = {k: to_array(v[i]) for k, v in inputs.items()}
                try:
                    one = sess.run(None, iii)
                    if lambda_onnx is None:
                        lambda_onnx = lambda: sess.run(None, iii)
                except ExpectedAssertionError as expe:
                    raise expe
                except Exception as e:
                    raise OnnxRuntimeAssertionError("Unable to run onnx '{0}' due to {1}".format(onx, e))
                res.append(one)
            output = _post_process_output(res)   
    else:
        try:
            output = sess.run(None, inputs)
            lambda_onnx = lambda: sess.run(None, inputs)
        except ExpectedAssertionError as expe:
            raise expe
        except RuntimeError as e:
            if "-Fail" in onx:
                raise ExpectedAssertionError("onnxruntime cannot compute the prediction for '{0}'".format(onx))
            else:
                raise OnnxRuntimeAssertionError("onnxruntime cannot compute the prediction for '{0}' due to {1}".format(onx, e))
        except Exception as e:
            raise OnnxRuntimeAssertionError("Unable to run onnx '{0}' due to {1}".format(onnx, e))
    
    output0 = output.copy()

    try:
        _compare_expected(load["expected"], output, sess, onx, decimal=decimal, **options)
    except ExpectedAssertionError as expe:
        raise expe
    except Exception as e:
        if verbose:
            import onnx
            model = onnx.load(onx)
            smodel = "\nJSON ONNX\n" + str(model)
        else:
            smodel = ""
        raise OnnxRuntimeAssertionError("Model '{0}' has discrepencies.\n{1}: {2}{3}".format(onx, type(e), e, smodel))
        
    return output0, lambda_onnx
    
        
def _post_process_output(res):
    """
    Applies post processings before running the comparison
    such as changing type from list to arrays.
    """
    if isinstance(res, list):
        if len(res) == 0:
            return res
        elif len(res) == 1:
            return _post_process_output(res[0])
        elif isinstance(res[0], numpy.ndarray):
            return numpy.array(res)
        elif isinstance(res[0], dict):
            import pandas
            return pandas.DataFrame(res).values
        else:
            ls = [len(r) for r in res]
            mi = min(ls)
            if mi != max(ls):
                raise NotImplementedError("Unable to postprocess various number of outputs in [{0}, {1}]".format(min(ls), max(ls)))
            if mi > 1:
                output = []
                for i in range(mi):
                    output.append(_post_process_output([r[i] for r in res]))
                return output
            elif isinstance(res[0], list):
                # list of lists
                if isinstance(res[0][0], list):
                    return numpy.array(res)
                elif len(res[0]) == 1 and isinstance(res[0][0], dict):
                    return _post_process_output([r[0] for r in res])
                elif len(res) == 1:
                    return res
                else:
                    if len(res[0]) != 1:
                        raise NotImplementedError("Not conversion implemented for {0}".format(res))
                    st = [r[0] for r in res]
                    return numpy.vstack(st)
            else:
                return res
    else:
        return res

def _create_column(values, dtype):
    "Creates a column from values with dtype"
    if str(dtype) == "tensor(int64)":
        return numpy.array(values, dtype=numpy.int64)
    elif str(dtype) == "tensor(float)":
        return numpy.array(values, dtype=numpy.float32)
    else:
        raise OnnxRuntimeAssertionError("Unable to create one column from dtype '{0}'".format(dtype))


def _compare_expected(expected, output, sess, onnx, decimal=5, **kwargs):
    """
    Compares the expected output against the runtime outputs.
    This is specific to *onnxruntime* due to variable *sess*
    of type *onnxruntime.InferenceSession*.
    """
    tested = 0
    if isinstance(expected, list):
        if isinstance(output, list):
            if 'Out0' in kwargs:
                expected = expected[:1]
                output = output[:1]
                del kwargs['Out0']
            if 'Reshape' in kwargs:
                del kwargs['Reshape']
                output = numpy.hstack(output).ravel()
                output = output.reshape((len(expected),
                                         len(output.ravel()) // len(expected)))
            if len(expected) != len(output):
                raise OnnxRuntimeAssertionError("Unexpected number of outputs '{0}', expected={1}, got={2}".format(onnx, len(expected), len(output)))
            for exp, out in zip(expected, output):
                _compare_expected(exp, out, sess, onnx, decimal=5, **kwargs)
                tested += 1
        else:
            raise OnnxRuntimeAssertionError("Type mismatch for '{0}', output type is {1}".format(onnx, type(output)))
    elif isinstance(expected, dict):
        if not isinstance(output, dict):
            raise OnnxRuntimeAssertionError("Type mismatch for '{0}'".format(onnx))                
        for k, v in output.items():
            if k not in expected:
                continue
            msg = compare_outputs(expected[k], v, decimal=decimal, **kwargs)
            if msg:
                raise OnnxRuntimeAssertionError("Unexpected output '{0}' in model '{1}'\n{2}".format(k, onnx, msg))
            tested += 1
    elif isinstance(expected, numpy.ndarray):
        if isinstance(output, list):
            if expected.shape[0] == len(output) and isinstance(output[0], dict):
                import pandas
                output = pandas.DataFrame(output)
                output = output[list(sorted(output.columns))]
                output = output.values
        if isinstance(output, (dict, list)):
            if len(output) != 1:
                ex = str(output)
                if len(ex) > 70:
                    ex = ex[:70] + "..."
                raise OnnxRuntimeAssertionError("More than one output when 1 is expected for onnx '{0}'\n{1}".format(onnx, ex))
            output = output[-1]
        if not isinstance(output, numpy.ndarray):
            raise OnnxRuntimeAssertionError("output must be an array for onnx '{0}' not {1}".format(onnx, type(output)))
        msg = compare_outputs(expected, output, decimal=decimal, **kwargs)
        if isinstance(msg, ExpectedAssertionError):
            raise msg
        if msg:
            raise OnnxRuntimeAssertionError("Unexpected output in model '{0}'\n{1}".format(onnx, msg))
        tested += 1
    else:
        from scipy.sparse.csr import csr_matrix
        if isinstance(expected, csr_matrix):
            # DictVectorizer
            one_array = numpy.array(output)
            msg = compare_outputs(expected.todense(), one_array, decimal=decimal, **kwargs)
            if msg:
                raise OnnxRuntimeAssertionError("Unexpected output in model '{0}'\n{1}".format(onnx, msg))
            tested += 1
        else:
            raise OnnxRuntimeAssertionError("Unexpected type for expected output ({1}) and onnx '{0}'".format(onnx, type(expected)))
    if tested ==0:
        raise OnnxRuntimeAssertionError("No test for onnx '{0}'".format(onnx))        
    
