"""
 Copyright (c) 2021 Intel Corporation
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
from abc import ABC
from copy import copy
from typing import TypeVar
from functools import partial
from abc import abstractmethod

import numpy as np
from scipy.interpolate import interp1d

from nncf.api.compression import CompressionAlgorithmController
from nncf.api.composite_compression import CompositeCompressionAlgorithmController
from nncf.common.utils.logger import logger as nncf_logger
from nncf.common.utils.registry import Registry
from nncf.config.config import NNCFConfig
from nncf.accuracy_aware_training.runner import PTAccuracyAwareTrainingRunner as \
    AccuracyAwareTrainingRunner


ModelType = TypeVar('ModelType')
ADAPTIVE_COMPRESSION_CONTROLLERS = Registry('adaptive_compression_controllers')


class TrainingLoop(ABC):
    """
    The training loop object is instantiated by the user, the training process
    is launched via the `run` method.
    """
    @abstractmethod
    def run(self, model: ModelType, train_epoch_fn, validate_fn,
            configure_optimizers_fn=None, tensorboard_writer=None, log_dir=None):
        pass


class AdaptiveCompressionTrainingLoop(TrainingLoop):
    """
    Adaptive compression training loop allows an accuracy-aware training process whereby
    the compression rate is automatically varied during training to reach the maximal
    possible compression rate with a positive accuracy budget
    (the maximal allowed accuracy degradation criterion is satisfied).
    """
    def __init__(self,
                 nncf_config: NNCFConfig,
                 compression_controller: CompressionAlgorithmController,
                 runner_cls=None):
        self.adaptive_controller, accuracy_aware_config = self.get_adaptive_compression_ctrl(compression_controller,
                                                                                             nncf_config)
        runner_cls = AccuracyAwareTrainingRunner if runner_cls is None else runner_cls
        self.runner = runner_cls(accuracy_aware_config)
        if self.adaptive_controller is None:
            raise RuntimeError('No compression algorithm supported by the accuracy-aware training '
                               'runner was specified in the config')

    @staticmethod
    def get_adaptive_compression_ctrl(compression_controller, nncf_config):
        adaptive_compression_controllers = ADAPTIVE_COMPRESSION_CONTROLLERS.registry_dict
        compression_configs = nncf_config.get('compression', {})
        if isinstance(compression_configs, list):
            comp_algorithm_params_dict = {compression_config['algorithm']: compression_config
                                        for compression_config in compression_configs}
        else:
            comp_algorithm_params_dict = {compression_configs['algorithm']: compression_configs}

        if not isinstance(compression_controller, CompositeCompressionAlgorithmController):
            for algo_name, ctrl_type in adaptive_compression_controllers.items():
                if isinstance(compression_controller, ctrl_type):
                    acc_aware_config = comp_algorithm_params_dict[algo_name].get('accuracy_aware_training', None)
                    return compression_controller, acc_aware_config
        if isinstance(compression_controller, CompositeCompressionAlgorithmController):
            for controller in compression_controller.child_ctrls:
                for algo_name, ctrl_type in adaptive_compression_controllers.items():
                    if isinstance(controller, ctrl_type):
                        acc_aware_config = comp_algorithm_params_dict[algo_name].get('accuracy_aware_training', None)
                        return controller, acc_aware_config
        raise RuntimeError('No compression algorithm that supports adaptive compression '
                           'accuracy-aware training was specified')

    # pylint: disable=E1101
    def run(self, model, train_epoch_fn, validate_fn,
            configure_optimizers_fn=None, tensorboard_writer=None, log_dir=None):

        self.runner.initialize_training_loop_fns(train_epoch_fn, validate_fn, configure_optimizers_fn,
                                                 tensorboard_writer, log_dir)
        self.runner.retrieve_original_accuracy(model)
        self.run_initial_training_phase(model, self.adaptive_controller, self.runner)
        self.runner.add_tensorboard_scalar('compression/accuracy_aware/target_compression_rate',
                                           self.adaptive_controller.compression_rate,
                                           self.runner.cumulative_epoch_count)
        self.runner.update_training_history(compression_rate=self.adaptive_controller.compression_rate,
                                            best_metric_value=self.runner.best_val_metric_value)

        self.runner.validate_every_n_epochs = 1
        while self.runner.compression_rate_step >= self.runner.minimal_compression_rate_step and \
            self.runner.cumulative_epoch_count < self.runner.maximal_total_epochs:

            if self.runner.compression_rate_target is not None:
                self.runner.update_training_history(compression_rate=copy(self.runner.compression_rate_target),
                                                    best_metric_value=copy(self.runner.best_val_metric_value))

            was_compression_rate_changed = self.update_target_compression_rate(self.adaptive_controller, self.runner)
            nncf_logger.info('Current target compression rate value: '
                                '{comp_rate:.3f}'.format(comp_rate=self.runner.compression_rate_target))
            nncf_logger.info('Current accuracy budget value: {acc_budget:.3f}'.format(acc_budget=self.runner.accuracy_bugdet))
            nncf_logger.info('Current compression rate step value: '
                                '{comp_step:.3f}'.format(comp_step=self.runner.compression_rate_step))

            if was_compression_rate_changed:
                if self.runner.compression_rate_target < self.runner.minimal_compression_rate:
                    raise RuntimeError('Cannot produce a compressed model with a specified '
                                        'minimal tolerable accuracy')
                if self.runner.compression_rate_target > self.runner.maximal_compression_rate:
                    nncf_logger.info('Reached maximal possible compression rate '
                                        '{max_rate}'.format(max_rate=self.runner.maximal_compression_rate))
                    return model

                self.runner.reset_training()
                self.adaptive_controller.compression_rate = self.runner.compression_rate_target
                self.runner.add_tensorboard_scalar('compression/accuracy_aware/target_compression_rate',
                                              self.runner.compression_rate_target, self.runner.cumulative_epoch_count)
                self.runner.add_tensorboard_scalar('compression/accuracy_aware/compression_rate_step',
                                              self.runner.compression_rate_step, self.runner.cumulative_epoch_count)

            compressed_model_accuracy = self.runner.train_epoch(model, self.adaptive_controller)
            self.runner.accuracy_bugdet = compressed_model_accuracy - self.runner.minimal_tolerable_accuracy
            self.runner.add_tensorboard_scalar('val/accuracy_aware/accuracy_bugdet', self.runner.accuracy_bugdet,
                                               self.runner.cumulative_epoch_count)

        self.runner.load_best_checkpoint(model)
        return model

    @staticmethod
    def run_initial_training_phase(model, accuracy_aware_controller, runner):
        runner.configure_optimizers()
        for _ in range(runner.initial_training_phase_epochs):
            runner.train_epoch(model, accuracy_aware_controller)
        compressed_model_accuracy = runner.validate(model, accuracy_aware_controller)
        runner.accuracy_bugdet = compressed_model_accuracy - runner.minimal_tolerable_accuracy
        runner.add_tensorboard_scalar('val/accuracy_aware/accuracy_bugdet',
                                    runner.accuracy_bugdet, runner.cumulative_epoch_count)
        nncf_logger.info('Accuracy budget value after training is {}'.format(runner.accuracy_bugdet))

    def update_target_compression_rate(self, accuracy_aware_controller, runner):
        current_compression_rate = accuracy_aware_controller.compression_rate
        best_accuracy_budget = runner.best_val_metric_value - runner.minimal_tolerable_accuracy
        if runner.compression_rate_target is None:
            runner.compression_rate_target = current_compression_rate + \
                self.determine_compression_rate_step_value(runner, current_compression_rate)
            runner.was_compression_increased_on_prev_step = np.sign(best_accuracy_budget)
            accuracy_aware_controller.disable_scheduler()
            return True
        if runner.training_epoch_count >= runner.patience_epochs:
            runner.compression_rate_target += self.determine_compression_rate_step_value(runner, current_compression_rate)
            runner.was_compression_increased_on_prev_step = np.sign(best_accuracy_budget)
            return True
        return False

    def determine_compression_rate_step_value(self, runner, current_compression_rate,
                                              stepping_mode='interpolate', **kwargs):
        compression_step_updaters = {
            'uniform_decrease': self.uniform_decrease_compression_step_update,
            'interpolate': partial(self.interpolate_compression_step_update,
                                current_compression_rate=current_compression_rate),
        }
        return compression_step_updaters[stepping_mode](runner, **kwargs)

    @staticmethod
    def uniform_decrease_compression_step_update(runner):
        best_accuracy_budget_sign = np.sign(runner.best_val_metric_value - runner.minimal_tolerable_accuracy)
        if runner.was_compression_increased_on_prev_step is not None and \
            runner.was_compression_increased_on_prev_step != best_accuracy_budget_sign:
            runner.compression_rate_step *= runner.step_reduction_factor
        return best_accuracy_budget_sign * runner.compression_rate_step

    @staticmethod
    def interpolate_compression_step_update(runner,
                                            current_compression_rate,
                                            num_curve_pts=1000,
                                            full_compression_factor=10,
                                            minimal_compression_rate=0.0,
                                            maximal_compression_rate=1.0):
        training_history = runner.compressed_training_history
        nncf_logger.info('Compressed training history: {}'.format(training_history))
        training_history[minimal_compression_rate] = runner.maximal_accuracy_drop
        training_history[maximal_compression_rate] = -full_compression_factor * runner.maximal_accuracy_drop
        compression_rates, evaluated_acc_budgets = list(training_history.keys()), list(training_history.values())
        interp_kind = 'linear' if len(compression_rates) < 4 else 'cubic'
        acc_budget_vs_comp_rate_curve = interp1d(compression_rates, evaluated_acc_budgets,
                                                kind=interp_kind)
        rate_interval = np.linspace(minimal_compression_rate, maximal_compression_rate,
                                    num=num_curve_pts, endpoint=True)
        acc_budget_values = acc_budget_vs_comp_rate_curve(rate_interval)
        target_compression_rate = rate_interval[np.argmin(np.abs(acc_budget_values))]
        nncf_logger.info('Predicted compression rate {}, '
                        'current compression rate {}'.format(target_compression_rate,
                                                            current_compression_rate))
        if runner.compression_rate_target is None:
            runner.compression_rate_step = np.abs(target_compression_rate - current_compression_rate)
            return target_compression_rate - current_compression_rate
        runner.compression_rate_step = np.abs(target_compression_rate - runner.compression_rate_target)
        return target_compression_rate - runner.compression_rate_target
