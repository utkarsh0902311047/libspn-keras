from typing import Optional
from typing import Tuple

import tensorflow as tf
from tensorflow_probability import distributions
from tensorflow_probability.python.internal.reparameterization import (
    NOT_REPARAMETERIZED,
)

from libspn_keras.layers.base_leaf import BaseLeaf


class IndicatorLeaf(BaseLeaf):
    """
    Indicator leaf distribution taking integer inputs and producing a discrete indicator representation.

    This effectively comes down to computing a one-hot representation along the final axis.

    Args:
        num_components (int): Number of components, or indicators in this context.
        dtype: Dtype of input
        **kwargs: Kwargs to pass onto the ``keras.layers.Layer`` superclass.
    """

    def __init__(self, num_components: int, dtype: tf.DType = tf.int32, **kwargs):
        super().__init__(num_components, dtype=dtype, **kwargs)

    def _build_distribution(self, shape: Tuple[Optional[int], ...]) -> None:
        self._indicator = _Indicator(self.num_components, dtype=self.dtype)

    def _get_distribution(self) -> distributions.Distribution:
        return self._indicator

    def get_leaf_representation(self, size: tf.Tensor) -> tf.Tensor:
        """
        Obtain the leaf representation.

        This can be used for e.g. MPE estimates of inputs.

        Arguments:
            size: 0D tensor with size of representation. Typically, this corresponds to the batch size.

        Returns:
            Tensor that represents leaf values (to be used when inferring values outside evidence)
        """
        pre_tile_shape = [1] * (len(self.output_shape) - 1) + [self.num_components, 1]

        return tf.tile(
            tf.reshape(tf.range(self.num_components, dtype=tf.float32), pre_tile_shape),
            (size,) + self.output_shape[1:-1] + (1, 1),
        )


class _Indicator(distributions.Distribution):
    def __init__(
        self, num_components: int, dtype: tf.DType = tf.int32, name: str = "Indicator"
    ):
        self._num_components = num_components
        super(_Indicator, self).__init__(
            dtype=dtype,
            name=name,
            reparameterization_type=NOT_REPARAMETERIZED,
            allow_nan_stats=True,
            validate_args=False,
        )

    def _log_prob(self, x: tf.Tensor) -> tf.Tensor:
        indicator_values = tf.one_hot(
            x, depth=self._num_components, on_value=0.0, off_value=float("-inf")
        )
        rank = len(indicator_values.shape)
        indicator_values = tf.transpose(
            indicator_values, list(range(rank - 2)) + [rank - 1, rank - 2]
        )
        return tf.squeeze(indicator_values, axis=3)
