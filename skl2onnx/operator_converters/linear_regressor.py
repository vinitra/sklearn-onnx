# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
try:
    import collections.abc as cabc
except ImportError:
    import collections as cabc
import numpy as np
from ..common._apply_operation import apply_cast
from ..common.data_types import (
    BooleanTensorType, Int64TensorType, guess_numpy_type)
from ..common._registration import register_converter
from ..proto import onnx_proto


def convert_sklearn_linear_regressor(scope, operator, container):
    op = operator.raw_operator
    op_type = 'LinearRegressor'
    dtype = guess_numpy_type(operator.inputs[0].type)
    if dtype not in (np.float32, np.float64):
        dtype = np.float32
    attrs = {'name': scope.get_unique_operator_name(op_type)}
    attrs['coefficients'] = op.coef_.astype(dtype).ravel()
    attrs['intercepts'] = (op.intercept_.astype(dtype)
                           if isinstance(op.intercept_, cabc.Iterable)
                           else np.array([op.intercept_], dtype=dtype))
    if len(op.coef_.shape) == 2:
        attrs['targets'] = op.coef_.shape[0]

    input_name = operator.input_full_names
    if type(operator.inputs[0].type) in (BooleanTensorType, Int64TensorType):
        cast_input_name = scope.get_unique_variable_name('cast_input')

        apply_cast(scope, operator.input_full_names, cast_input_name,
                   container,
                   to=(onnx_proto.TensorProto.DOUBLE
                       if dtype == np.float64
                       else onnx_proto.TensorProto.FLOAT))
        input_name = cast_input_name
    container.add_node(op_type, input_name,
                       operator.output_full_names, op_domain='ai.onnx.ml',
                       **attrs)


register_converter('SklearnLinearRegressor', convert_sklearn_linear_regressor)
register_converter('SklearnLinearSVR', convert_sklearn_linear_regressor)
