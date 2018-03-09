from __future__ import absolute_import, division, print_function

import copy
import logging
import warnings
from collections import OrderedDict
from inspect import isclass

import torch
from torch.autograd import Variable

import pyro.poutine as poutine
from pyro.distributions.distribution import Distribution
from pyro.params import _MODULE_NAMESPACE_DIVIDER, _PYRO_PARAM_STORE, param_with_module_name
from pyro.poutine import _PYRO_STACK, condition, do  # noqa: F401
from pyro.util import apply_stack, deep_getattr, get_tensor_data, ones, set_rng_seed, zeros, am_i_wrapped  # noqa: F401

__version__ = '0.1.2'

# Default logger to prevent 'No handler found' warning.
logging.getLogger(__name__).addHandler(logging.NullHandler())


def get_param_store():
    """
    Returns the ParamStore
    """
    return _PYRO_PARAM_STORE


def clear_param_store():
    """
    Clears the ParamStore. This is especially useful if you're working in a REPL.
    """
    return _PYRO_PARAM_STORE.clear()


def sample(name, fn, *args, **kwargs):
    """
    Calls the stochastic function `fn` with additional side-effects depending
    on `name` and the enclosing context (e.g. an inference algorithm).
    See `Intro I <http://pyro.ai/examples/intro_part_i.html>`_ and
    `Intro II <http://pyro.ai/examples/intro_part_ii.html>`_ for a discussion.

    :param name: name of sample
    :param fn: distribution class or function
    :param obs: observed datum (optional; should only be used in context of
        inference) optionally specified in kwargs
    :param dict infer: Optional dictionary of inference parameters specified
        in kwargs. See inference documentation for details.
    :returns: sample
    """
    obs = kwargs.pop("obs", None)
    infer = kwargs.pop("infer", {})
    # check if stack is empty
    # if stack empty, default behavior (defined here)
    if not am_i_wrapped():
        if obs is not None:
            warnings.warn("trying to observe a value outside of inference at " + name,
                          RuntimeWarning)
            return obs
        return fn(*args, **kwargs)
    # if stack not empty, apply everything in the stack?
    else:
        # initialize data structure to pass up/down the stack
        msg = {
            "type": "sample",
            "name": name,
            "fn": fn,
            "is_observed": False,
            "args": args,
            "kwargs": kwargs,
            "value": None,
            "infer": infer,
            "scale": 1.0,
            "cond_indep_stack": (),
            "done": False,
            "stop": False,
            "continuation": None
        }
        # handle observation
        if obs is not None:
            msg["value"] = obs
            msg["is_observed"] = True
        # apply the stack and return its return value
        apply_stack(msg)
        return msg["value"]


def observe(name, fn, obs, *args, **kwargs):
    """
    Alias of `pyro.sample(name, fn, *args, obs=obs, **kwargs)`.

    :param name: name of observation
    :param fn: distribution class or function
    :param obs: observed datum
    :returns: sample
    """
    kwargs.update({"obs": obs})
    return sample(name, fn, *args, **kwargs)


class _Subsample(Distribution):
    """
    Randomly select a subsample of a range of indices.

    Internal use only. This should only be used by `iarange`.
    """

    def __init__(self, size, subsample_size, use_cuda=None):
        """
        :param int size: the size of the range to subsample from
        :param int subsample_size: the size of the returned subsample
        :param bool use_cuda: whether to use cuda tensors
        """
        self.size = size
        self.subsample_size = subsample_size
        self.use_cuda = torch.Tensor.is_cuda if use_cuda is None else use_cuda

    def sample(self, sample_shape=torch.Size()):
        """
        :returns: a random subsample of `range(size)`
        :rtype: torch.autograd.Variable of torch.LongTensor
        """
        if sample_shape:
            raise NotImplementedError
        subsample_size = self.subsample_size
        if subsample_size is None or subsample_size > self.size:
            subsample_size = self.size
        if subsample_size == self.size:
            result = Variable(torch.LongTensor(list(range(self.size))))
        else:
            result = Variable(torch.randperm(self.size)[:self.subsample_size])
        return result.cuda() if self.use_cuda else result

    def log_prob(self, x):
        # This is zero so that iarange can provide an unbiased estimate of
        # the non-subsampled log_prob.
        result = Variable(torch.zeros(1))
        return result.cuda() if self.use_cuda else result


def _subsample(name, size=None, subsample_size=None, subsample=None, use_cuda=None):
    """
    Helper function for iarange and irange. See their docstrings for details.
    """
    if size is None:
        assert subsample_size is None
        assert subsample is None
        size = -1  # This is PyTorch convention for "arbitrary size"
        subsample_size = -1
    elif subsample is None:
        names = [name]
        names += [str(f.counter) for f in _PYRO_STACK if isinstance(f, poutine.IndepMessenger)]
        subsample = sample("_".join(names), _Subsample(size, subsample_size, use_cuda))

    if subsample_size is None:
        subsample_size = len(subsample)
    elif subsample is not None and subsample_size != len(subsample):
        raise ValueError("subsample_size does not match len(subsample), {} vs {}.".format(
            subsample_size, len(subsample)) +
            " Did you accidentally use different subsample_size in the model and guide?")

    return size, subsample_size, subsample


class _DimAllocator(object):
    """
    Dimension allocator for internal use by :class:`iarange`.

    Note that dimensions are indexed from the right, e.g. -1, -2.
    """
    def __init__(self):
        self._stack = []  # in reverse orientation of log_prob.shape

    def allocate(self, name, dim):
        """
        Allocate a dimension to an :class:`iarange` with given name.
        Dim should be either None for automatic allocation or a negative
        integer for manual allocation.
        """
        if name in self._stack:
            raise ValueError('duplicate iarange "{}"'.format(name))
        if dim is None:
            # Automatically allocate the rightmost dimension to the left of all existing dims.
            self._stack.append(name)
            dim = -len(self._stack)
        elif dim >= 0:
            raise ValueError('Expected dim < 0 to index from the right, actual {}'.format(dim))
        else:
            # Allocate the requested dimension.
            while dim < -len(self._stack):
                self._stack.append(None)
            if self._stack[-1 - dim] is not None:
                raise ValueError('\n'.join([
                    'at iaranges "{}" and "{}", collide at dim={}'.format(name, self._stack[-1 - dim], dim),
                    '\nTry moving the dim of one iarange to the left, e.g. dim={}'.format(dim - 1)]))
            self._stack[-1 - dim] = name
        return dim

    def free(self, name, dim):
        """
        Free a dimension.
        """
        assert self._stack[-1 - dim] == name
        self._stack[-1 - dim] = None
        while self._stack and self._stack[-1] is None:
            self._stack.pop()


_DIM_ALLOCATOR = _DimAllocator()


class iarange(object):
    """
    Context manager for conditionally independent ranges of variables.

    :class:`iarange` is similar to :func:`torch.arange` in that it yields an
    array of indices by which other tensors can be indexed. :class:`iarange`
    differs from :func:`torch.arange` in that it also informs inference
    algorithms that the variables being indexed are conditionally independent.
    To do this, :class:`iarange` is a provided as context manager rather than a
    function, and users must guarantee that all computation within an
    :class:`iarange` context is conditionally independent::

        with iarange("name", size) as ind:
            # ...do conditionally independent stuff with ind...

    Additionally, :class:`iarange` can take advantage of the conditional
    independence assumptions by subsampling the indices and informing inference
    algorithms to scale various computed values. This is typically used to
    subsample minibatches of data::

        with iarange("data", len(data), subsample_size=100) as ind:
            batch = data[ind]
            assert len(batch) == 100

    By default ``subsample_size=False`` and this simply yields a
    ``torch.arange(0, size)``. If ``0 < subsample_size <= size`` this yields a
    single random batch of indices of size ``subsample_size`` and scales all
    log likelihood terms by ``size/batch_size``, within this context.

    .. warning::  This is only correct if all computation is conditionally
        independent within the context.

    :param str name: A unique name to help inference algorithms match
        :class:`iarange` sites between models and guides.
    :param int size: Optional size of the collection being subsampled
        (like `stop` in builtin `range`).
    :param int subsample_size: Size of minibatches used in subsampling.
        Defaults to `size`.
    :param subsample: Optional custom subsample for user-defined subsampling
        schemes. If specified, then `subsample_size` will be set to
        `len(subsample)`.
    :type subsample: Anything supporting `len()`.
    :param int dim: An optional dimension to use for this independence index.
        If specified, ``dim`` should be negative, i.e. should index from the
        right. If not specified, ``dim`` is set to the rightmost dim that is
        left of all enclosing ``iarange`` contexts.
    :param bool use_cuda: Optional bool specifying whether to use cuda tensors
        for `subsample` and `log_pdf`. Defaults to `torch.Tensor.is_cuda`.
    :return: A reusabe context manager yielding a single 1-dimensional
        :class:`torch.Tensor` of indices.

    Examples::

        # This version simply declares independence:
        >>> with iarange('data'):
                sample('obs', Normal(mu, sigma), obs=data)

        # This version subsamples data in vectorized way:
        >>> with iarange('data', 100, subsample_size=10) as ind:
                sample('obs', Normal(mu, sigma), obs=data[ind])

        # This wraps a user-defined subsampling method for use in pyro:
        >>> ind = my_custom_subsample
        >>> with iarange('data', 100, subsample=ind):
                sample('obs', Normal(mu, sigma), obs=data[ind])

        # This reuses two different independence contexts.
        >>> x_axis = iarange('outer', 320, dim=-1)
        >>> y_axis = iarange('outer', 200, dim=-2)
        >>> with x_axis:
                x_noise = sample("x_noise", Normal(mu, sigma).reshape([320]))
        >>> with y_axis:
                y_noise = sample("y_noise", Normal(mu, sigma).reshape([200, 1]))
        >>> with x_axis, y_axis:
                xy_noise = sample("xy_noise", Normal(mu, sigma).reshape([200, 320]))

    See `SVI Part II <http://pyro.ai/examples/svi_part_ii.html>`_ for an
    extended discussion.
    """
    def __init__(self, name, size=None, subsample_size=None, subsample=None, dim=None, use_cuda=None):
        self.name = name
        self.dim = dim
        self.size, self.subsample_size, self.subsample = _subsample(name, size, subsample_size, subsample, use_cuda)

    def __enter__(self):
        self._wrapped = am_i_wrapped()
        self.dim = _DIM_ALLOCATOR.allocate(self.name, self.dim)
        if self._wrapped:
            self._scale_poutine = poutine.ScaleMessenger(self.size / self.subsample_size)
            self._indep_poutine = poutine.IndepMessenger(self.name, size=self.subsample_size, dim=self.dim)
            self._scale_poutine.__enter__()
            self._indep_poutine.__enter__()
        return self.subsample

    def __exit__(self, exc_type, exc_value, traceback):
        if self._wrapped:
            self._indep_poutine.__exit__(exc_type, exc_value, traceback)
            self._scale_poutine.__exit__(exc_type, exc_value, traceback)
        _DIM_ALLOCATOR.free(self.name, self.dim)


def irange(name, size, subsample_size=None, subsample=None, use_cuda=None):
    """
    Non-vectorized version of ``iarange``. See ``iarange`` for details.

    :param str name: A name that will be used for this site in a Trace.
    :param int size: The size of the collection being subsampled (like ``stop``
        in builtin ``range``).
    :param int subsample_size: Size of minibatches used in subsampling.
        Defaults to ``size``.
    :param subsample: Optional custom subsample for user-defined subsampling
        schemes. If specified, then ``subsample_size`` will be set to
        ``len(subsample)``.
    :type subsample: Anything supporting ``len()``.
    :param bool use_cuda: Optional bool specifying whether to use cuda tensors
        for internal ``log_pdf`` computations. Defaults to
        ``torch.Tensor.is_cuda``.
    :return: A generator yielding a sequence of integers.

    Examples::

        >>> for i in irange('data', 100, subsample_size=10):
                if z[i]:  # Prevents vectorization.
                    observe('obs_{}'.format(i), normal, data[i], mu, sigma)

    See `SVI Part II <http://pyro.ai/examples/svi_part_ii.html>`_ for an extended discussion.
    """
    size, subsample_size, subsample = _subsample(name, size, subsample_size, subsample, use_cuda)
    if not am_i_wrapped():
        for i in subsample:
            yield i.item() if isinstance(i, Variable) else i
    else:
        indep_context = poutine.IndepMessenger(name, size=subsample_size)
        with poutine.ScaleMessenger(size / subsample_size):
            for i in subsample:
                indep_context.next_context()
                with indep_context:
                    # convert to python numeric type as functions like torch.ones(*args)
                    # do not work with dim 0 torch.Tensor instances.
                    yield i.item() if isinstance(i, Variable) else i


# XXX this should have the same call signature as torch.Tensor constructors
def param(name, *args, **kwargs):
    """
    Saves the variable as a parameter in the param store.
    To interact with the param store or write to disk,
    see `Parameters <parameters.html>`_.

    :param name: name of parameter
    :returns: parameter
    """
    if not am_i_wrapped():
        return _PYRO_PARAM_STORE.get_param(name, *args, **kwargs)
    else:
        msg = {
            "type": "param",
            "name": name,
            "args": args,
            "kwargs": kwargs,
            "infer": {},
            "scale": 1.0,
            "cond_indep_stack": (),
            "value": None,
            "done": False,
            "stop": False,
            "continuation": None
        }
        # apply the stack and return its return value
        apply_stack(msg)
        return msg["value"]


def module(name, nn_module, tags="default", update_module_params=False):
    """
    Takes a torch.nn.Module and registers its parameters with the ParamStore.
    In conjunction with the ParamStore save() and load() functionality, this
    allows the user to save and load modules.

    :param name: name of module
    :type name: str
    :param nn_module: the module to be registered with Pyro
    :type nn_module: torch.nn.Module
    :param tags: optional; tags to associate with any parameters inside the module
    :type tags: string or iterable of strings
    :param update_module_params: determines whether Parameters
                                 in the PyTorch module get overridden with the values found in the
                                 ParamStore (if any). Defaults to `False`
    :type load_from_param_store: bool
    :returns: torch.nn.Module
    """
    assert hasattr(nn_module, "parameters"), "module has no parameters"
    assert _MODULE_NAMESPACE_DIVIDER not in name, "improper module name, since contains %s" %\
        _MODULE_NAMESPACE_DIVIDER

    if isclass(nn_module):
        raise NotImplementedError("pyro.module does not support class constructors for " +
                                  "the argument nn_module")

    target_state_dict = OrderedDict()

    for param_name, param_value in nn_module.named_parameters():
        # register the parameter in the module with pyro
        # this only does something substantive if the parameter hasn't been seen before
        full_param_name = param_with_module_name(name, param_name)
        returned_param = param(full_param_name, param_value, tags=tags)

        if get_tensor_data(param_value)._cdata != get_tensor_data(returned_param)._cdata:
            target_state_dict[param_name] = returned_param

    if target_state_dict and update_module_params:
        # WARNING: this is very dangerous. better method?
        for _name, _param in nn_module.named_parameters():
            is_param = False
            name_arr = _name.rsplit('.', 1)
            if len(name_arr) > 1:
                mod_name, param_name = name_arr[0], name_arr[1]
            else:
                is_param = True
                mod_name = _name
            if _name in target_state_dict.keys():
                if not is_param:
                    deep_getattr(nn_module, mod_name)._parameters[param_name] = target_state_dict[_name]
                else:
                    nn_module._parameters[mod_name] = target_state_dict[_name]

    return nn_module


def random_module(name, nn_module, prior, *args, **kwargs):
    """
    Places a prior over the parameters of the module `nn_module`.
    Returns a distribution (callable) over `nn.Module`s, which
    upon calling returns a sampled `nn.Module`.

    See the `Bayesian Regression tutorial <http://pyro.ai/examples/bayesian_regression.html>`_
    for an example.

    :param name: name of pyro module
    :type name: str
    :param nn_module: the module to be registered with pyro
    :type nn_module: torch.nn.Module
    :param prior: pyro distribution, stochastic function, or python dict with parameter names
                  as keys and respective distributions/stochastic functions as values.
    :returns: a callable which returns a sampled module
    """
    assert hasattr(nn_module, "parameters"), "Module is not a NN module."
    # register params in param store
    lifted_fn = poutine.lift(module, prior)

    def _fn():
        nn_copy = copy.deepcopy(nn_module)
        # update_module_params must be True or the lifted module will not update local params
        return lifted_fn(name, nn_copy, update_module_params=True, *args, **kwargs)
    return _fn
