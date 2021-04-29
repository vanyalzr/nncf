"""
 Copyright (c) 2020 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""
from typing import Callable, Any, Optional

import torch
from torch import nn
import torch.nn
from torch.nn.modules.loss import _Loss
from torch.utils.data import DataLoader

from nncf.config.structure import NNCFExtraConfigStruct


class QuantizationPrecisionInitArgs(NNCFExtraConfigStruct):
    """
    Stores arguments for initialization of quantization's bitwidth.
    Initialization is based on calculating a measure reflecting layers' sensitivity to perturbations. The measure is
    calculated by estimation of average trace of Hessian for modules using the Hutchinson algorithm.
    :param criterion_fn: callable object, that implements calculation of loss by given outputs of the model, targets,
    and loss function. It's not needed when the calculation of loss is just a direct call of the criterion with 2
    arguments: outputs of model and targets. For all other specific cases, the callable object should be provided.
    E.g. for inception-v3, the losses for two outputs of the model are combined with different weight.
    :param criterion: loss function, instance of descendant of `torch.nn.modules.loss._Loss`,
    :param data_loader: 'data_loader' - provides an iterable over the given dataset. Instance of
                nncf.initialization.InitializingDataLoader; a regular 'torch.utils.data.DataLoader' may
                also be passed, but only in the simple case when it returns a tuple of (input, target) tensors.
                *WARNING*: The final quantizer setup of the created compressed model is dependent on the data
                provided by the data_loader. When using PyTorch's DistributedDataParallel with precision
                initialization, make sure that each process in the distributed group receives the same data
                from the data_loader as the other processes, otherwise the create_compressed_model call may
                create different compressed model objects for each distributed process and the distributed training
                will fail.
    :param device: Device to perform initialization at. Either 'cpu', 'cuda', or None (default); if None, will
                   use the device of the model's parameters.
    """

    def __init__(self, criterion_fn: Callable[[Any, Any, _Loss], torch.Tensor], criterion: _Loss,
                 data_loader: DataLoader, device: str = None):
        self.criterion_fn = criterion_fn
        self.criterion = criterion
        self.data_loader = data_loader
        self.device = device

    @classmethod
    def get_id(cls) -> str:
        return "quantization_precision_init_args"


class QuantizationRangeInitArgs(NNCFExtraConfigStruct):
    """
    Stores arguments for initialization of quantization's ranges.
    Initialization is done by collecting per-layer activation statistics on training dataset in order to choose proper
    output range for quantization.
    :param data_loader: 'data_loader' - provides an iterable over the given dataset. Instance of
                nncf.initialization.InitializingDataLoader; a regular 'torch.utils.data.DataLoader' may
                also be passed, but only in the simple case when it returns a tuple of (input, target) tensors.
    :param device: Device to perform initialization at. Either 'cpu', 'cuda', or None (default); if None, will
                   use the device of the model's parameters.
    """

    def __init__(self, data_loader: DataLoader, device: str = None):
        self.data_loader = data_loader
        self.device = device

    @classmethod
    def get_id(cls) -> str:
        return "quantization_range_init_args"


class BNAdaptationInitArgs(NNCFExtraConfigStruct):
    """
    Stores arguments for BatchNorm statistics adaptation procedure.
    Adaptation is done by inferring a number of data batches on a compressed model
    while the BN layers are updating the rolling_mean and rolling_variance stats.
    :param data_loader: 'data_loader' - provides an iterable over the given dataset. Instance of
                nncf.initialization.InitializingDataLoader; a regular 'torch.utils.data.DataLoader' may
                also be passed, but only in the simple case when it returns a tuple of (input, target) tensors.
    :param device: Device to perform initialization at. Either 'cpu', 'cuda', or None (default); if None, will
                   use the device of the model's parameters.
    """

    def __init__(self, data_loader: DataLoader, device: str = None):
        self.data_loader = data_loader
        self.device = device

    @classmethod
    def get_id(cls) -> str:
        return "bn_adaptation_init_args"

class AutoQPrecisionInitArgs(NNCFExtraConfigStruct):
    """
    :param data_loader: 'data_loader' - provides an iterable over the given dataset. Instance of
                nncf.initialization.InitializingDataLoader; a regular 'torch.utils.data.DataLoader' may
                also be passed, but only in the simple case when it returns a tuple of (input, target) tensors.
                *WARNING*: The final quantizer setup of the created compressed model is dependent on the data
                provided by the data_loader. When using PyTorch's DistributedDataParallel with precision
                initialization, make sure that each process in the distributed group receives the same data
                from the data_loader as the other processes, otherwise the create_compressed_model call may
                create different compressed model objects for each distributed process and the distributed training
                will fail.
    """
    def __init__(self, data_loader: DataLoader,
                 eval_fn: Callable[[torch.nn.Module, torch.utils.data.DataLoader], float],
                 nncf_config: 'NNCFConfig'):
        self.data_loader = data_loader
        self.eval_fn = eval_fn
        self.config = nncf_config

    @classmethod
    def get_id(cls) -> str:
        return "autoq_precision_init_args"


class ModelEvaluationArgs(NNCFExtraConfigStruct):
    def __init__(self, data_loader: DataLoader,
                 eval_fn: Callable[[torch.nn.Module, torch.utils.data.DataLoader], float]):
        self.data_loader = data_loader
        self.eval_fn = eval_fn

    @classmethod
    def get_id(cls) -> str:
        return "model_evaluation_args"


class TrainEpochArgs(NNCFExtraConfigStruct):
    def __init__(self,
                 train_epoch_fn,
                 eval_fn,
                 configure_optimizers_fn,
                 tensorboard_writer,
                 log_dir):
        self.train_epoch_fn = train_epoch_fn
        self.eval_fn = eval_fn
        self.configure_optimizers_fn = configure_optimizers_fn
        self.tensorboard_writer = tensorboard_writer
        self.log_dir = log_dir

    @classmethod
    def get_id(cls) -> str:
        return "train_epoch_args"




class LeGRInitArgs(NNCFExtraConfigStruct):
    def __init__(self,
                 train_loader,
                 train_fn,
                 val_loader,
                 val_fn,
                 train_optimizer,
                 nncf_config: 'NNCFConfig'):
        self.train_loader = train_loader
        self.train_steps_fn = train_fn
        self.val_loader = val_loader
        self.val_fn = val_fn
        self.train_optimizer = train_optimizer
        self.config = nncf_config

    @classmethod
    def get_id(cls) -> str:
        return "legr_init_args"


class DistributedCallbacksArgs(NNCFExtraConfigStruct):
    def __init__(self,
                 wrapping_callback: Callable[[nn.Module], nn.Module],
                 unwrapping_callback: Callable[[nn.Module], nn.Module]):
        """
        Pair of callbacks that needed for distributed training of the model: wrapping model with wrapping_callback for
        distributed training, and after all training steps unwrapping model to the initial not-distributed state with
        unwrapping_callback.
        :param wrapping_callback: Callback that wraps model for distributed training with any necessary structure (for
        example, torch.nn.DataParallel or any custom class), returns wrapped model ready for distributed training
        :param unwrapping_callback: Callback for unwrapping model wrapped with wrapping_callback, returns original model
        """
        self.wrap_model = wrapping_callback
        self.unwrap_model = unwrapping_callback

    @classmethod
    def get_id(cls) -> str:
        return "distributed_callbacks_args"


class ExecutionParameters:
    def __init__(self, cpu_only: bool, current_gpu: Optional[int]):
        """
        Parameters that is necessary for distributed training of the model.
        :param cpu_only: whether cpu-only mode is using for training
        :param current_gpu: id of GPU that should be used for training (if only one of all is used)
        """
        self.cpu_only = cpu_only
        self.current_gpu = current_gpu
