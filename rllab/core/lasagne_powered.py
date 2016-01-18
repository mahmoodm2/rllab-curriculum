from rllab.core.parameterized import Parameterized
from rllab.misc.overrides import overrides
import lasagne.layers as L


class LasagnePowered(Parameterized):

    def __init__(self, output_layers):
        self._output_layers = output_layers
        super(LasagnePowered, self).__init__()

    @overrides
    def get_params_internal(self, **tags):
        return sorted(L.get_all_params(
            L.concat(self._output_layers),
            **tags
        ), key=lambda x: x.name)
