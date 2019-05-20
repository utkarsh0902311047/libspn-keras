import operator
from libspn.graph.node import OpNode, Input, BlockNode
from libspn.inference.type import InferenceType
import libspn.utils as utils
from libspn.log import get_logger
import functools
import tensorflow as tf


@utils.register_serializable
class BlockPermuteProduct(BlockNode):

    logger = get_logger()
    info = logger.info

    """An abstract node representing sums in an SPN.

    Args:
        *values (input_like): Inputs providing input values to this node.
            See :meth:`~libspn.Input.as_input` for possible values.
        num_sums (int): Number of Sum ops modelled by this node.
        sum_sizes (list): A list of ints corresponding to the sizes of each sum. If both num_sums
                          and sum_sizes are given, we should have len(sum_sizes) == num_sums.
        batch_axis (int): The index of the batch axis.
        op_axis (int): The index of the op axis that contains the individual sums being modeled.
        reduce_axis (int): The axis over which to perform summing (or max for MPE)
        name (str): Name of the node.

    Attributes:
        inference_type(InferenceType): Flag indicating the preferred inference
                                       type for this node that will be used
                                       during value calculation and learning.
                                       Can be changed at any time and will be
                                       used during the next inference/learning
                                       op generation.
    """

    def __init__(self, child, num_subsets, num_decomps=None, num_scopes=None,
                 inference_type=InferenceType.MARGINAL,
                 name="TensorProduct", input_format="SDBN", output_format="SDBN"):
        super().__init__(
            inference_type=inference_type, name=name, input_format=input_format,
            output_format=output_format, num_decomps=num_decomps, num_scopes=num_scopes)
        self.set_values(child)
        self._num_factors = num_subsets

    @property
    def dim_nodes(self):
        return self.child.dim_nodes ** self._num_factors

    @property
    def dim_decomps(self):
        return self.child.dim_decomps

    def _compute_out_size(self, *input_out_sizes):
        pass

    @property
    def child(self):
        return self.values[0].node
    
    @property
    def dim_scope(self):
        return self.child.dim_scope // self._num_factors

    @property
    def num_factors(self):
        return self._num_factors

    @utils.docinherit(OpNode)
    def serialize(self):
        raise NotImplementedError()

    @utils.docinherit(OpNode)
    def deserialize(self, data):
        raise NotImplementedError()

    @utils.docinherit(OpNode)
    def deserialize_inputs(self, data, nodes_by_name):
        raise NotImplementedError()

    @property
    @utils.docinherit(OpNode)
    def inputs(self):
        return self._values

    @property
    def values(self):
        """list of Input: List of value inputs."""
        return self._values

    def set_values(self, *values):
        """Set the inputs providing input values to this node. If no arguments
        are given, all existing value inputs get disconnected.

        Args:
            *values (input_like): Inputs providing input values to this node.
                See :meth:`~libspn.Input.as_input` for possible values.
        """
        if len(values) > 1:
            raise NotImplementedError("Can only deal with single inputs")
        if not isinstance(values[0], BlockNode):
            raise NotImplementedError("Inputs must be TensorNode")
        self._values = self._parse_inputs(*values)

    def add_values(self, *values):
        """Add more inputs providing input values to this node.

        Args:
            *values (input_like): Inputs providing input values to this node.
                See :meth:`~libspn.Input.as_input` for possible values.
        """
        self._values += self._parse_inputs(*values)
        self._reset_sum_sizes()

    @utils.docinherit(OpNode)
    @utils.lru_cache
    def _compute_log_value(self, child_log_prob):

        # Split in list of tensors which will be added up using outer products
        shape = [self.dim_scope, self._num_factors, self.dim_decomps, -1, self.child.dim_nodes]
        log_prob_per_in_scope = tf.split(
            tf.reshape(child_log_prob, shape=shape), axis=1, num_or_size_splits=self._num_factors)

        # Reshape to [scopes, decomps, batch, 1, ..., child.dim_nodes, ..., 1] where
        # child.dim_nodes is inserted at the i-th index within the trailing 1s, where i corresponds
        # to the index of the log prob
        log_prob_per_in_scope = [
            tf.reshape(
                log_prob,
                [self.dim_scope, self.dim_decomps, -1] +
                [1 if j != i else self.child.dim_nodes for j in range(self._num_factors)]
            )
            for i, log_prob in enumerate(log_prob_per_in_scope)
        ]
        # Add up everything (effectively computing an outer product) and flatten
        return tf.reshape(
            functools.reduce(operator.add, log_prob_per_in_scope),
            [self.dim_scope, self.dim_decomps, -1, self.child.dim_nodes ** self._num_factors])

    @utils.docinherit(OpNode)
    @utils.lru_cache
    def _compute_log_mpe_value(self, child_log_prob):
        return self._compute_log_value(child_log_prob)

    @utils.docinherit(OpNode)
    @utils.lru_cache
    def _compute_log_mpe_path(self, counts, *child_log_prob):
        # In the forward pass, we performed out products in #factors directions. For each direction,
        # we simply need to sum up the counts of the other directions from the parent to obtain the
        # counts for the child. This is a many-to-few operation.
        child = self.child
        counts_reshaped = tf.reshape(
            counts, [self.dim_scope, self.dim_decomps, -1] + [child.dim_nodes] * self._num_factors)

        # Reducing 'inverts' the outer products
        counts_reduced = [
            # reduce_axes_i == {j | j \in {0, 1, ..., #num_factors - 1} \ i}
            tf.reduce_sum(counts_reshaped, axis=[j + 3 for j in range(self._num_factors) if j != i])
            for i in range(self._num_factors)
        ]

        # Stacking 'inverts' the split
        return (tf.reshape(tf.stack(counts_reduced, axis=1),
                           (child.dim_scope, self.dim_decomps, -1, child.dim_nodes)),)

    @utils.docinherit(OpNode)
    def _compute_scope(self, *value_scopes):
        raise NotImplementedError()

    @utils.docinherit(OpNode)
    def _compute_valid(self, *value_scopes):
        # If already invalid, return None
        raise NotImplementedError()

    @property
    @utils.docinherit(OpNode)
    def _const_out_size(self):
        return True

