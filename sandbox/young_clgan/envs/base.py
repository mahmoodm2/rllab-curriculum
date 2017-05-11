import random
from rllab import spaces
import sys
import os.path as osp

import numpy as np
import scipy.misc
import tempfile
import math

from rllab.envs.mujoco.mujoco_env import MODEL_DIR, BIG
from rllab.core.serializable import Serializable
from rllab.envs.proxy_env import ProxyEnv
from rllab.envs.base import Step
from rllab.misc import autoargs
from rllab.misc import logger
from rllab.spaces.box import Box
from rllab.misc.overrides import overrides


class StateGenerator(object):
    """ Base class for goal generator. """

    def __init__(self):
        self._state = None
        self.update()

    def update(self):
        return self.state

    @property
    def state(self):
        return self._state


class UniformListStateGenerator(StateGenerator, Serializable):
    """ Generating goals uniformly from a goal list. """

    def __init__(self, state_list):
        Serializable.quick_init(self, locals())
        self.state_list = state_list
        self.state_size = np.size(self.state_list[0])  # assumes all goals have same dim as first in list
        random.seed()
        super(UniformListStateGenerator, self).__init__()

    def update(self):
        self._state = random.choice(self.state_list)
        return self.state


class UniformStateGenerator(StateGenerator, Serializable):
    """ Generating goals uniformly from a goal list. """

    def __init__(self, state_size, bounds=2, center=()):
        Serializable.quick_init(self, locals())
        self.state_size = state_size
        self.bounds = bounds
        if np.array(self.bounds).size == 1:
            self.bounds = [-1 * bounds * np.ones(state_size), bounds * np.ones(state_size)]
        self.center = center if len(center) else np.zeros(self.state_size)
        super(UniformStateGenerator, self).__init__()

    def update(self):  # This should be centered around the initial position!!
        sample = []
        for low, high in zip(*self.bounds):
            sample.append(np.random.uniform(low, high))
        self._state = self.center + np.array(sample)
        return self.state


class FixedStateGenerator(StateGenerator, Serializable):
    """ Generating a fixed goal. """

    def __init__(self, state):
        Serializable.quick_init(self, locals())
        super(FixedStateGenerator, self).__init__()
        self._state = state


class StateAuxiliaryEnv(Serializable):
    """ Base class for state auxiliary environment. Implements state update utilities. """

    def __init__(self, state_generator=None, *args, **kwargs):
        Serializable.quick_init(self, locals())
        if state_generator is not None:
            self._state_generator = state_generator

    def update_state_generator(self, state_generator):
        self._state_generator = state_generator

    def update_aux_state(self):
        return self.state_generator.update()

    @property
    def state_generator(self):
        return self._state_generator

    @property
    def current_aux_state(self):
        return self.state_generator.state

    def __getstate__(self):
        d = super(StateAuxiliaryEnv, self).__getstate__()
        d['__state_generator'] = self.state_generator
        return d

    def __setstate__(self, d):
        super(StateAuxiliaryEnv, self).__setstate__(d)
        self.update_state_generator(d['__state_generator'])
        
        
        
def update_env_state_generator(env, state_generator):
    """ Update the goal generator for normalized environment. """
    obj = env
    while not hasattr(obj, 'update_state_generator') and hasattr(obj, 'wrapped_env'):
        obj = obj.wrapped_env
    if hasattr(obj, 'update_state_generator'):
        return obj.update_state_generator(state_generator)
    else:
        raise NotImplementedError('Unsupported environment')

