from typing import List, Any

from copy import deepcopy
import torch
from functools import reduce

from nncf.api.compression import CompressionLoss
from nncf.api.compression import CompressionScheduler
from nncf.common.schedulers import BaseCompressionScheduler

from nncf.compression_method_api import PTCompressionAlgorithmBuilder
from nncf.compression_method_api import PTCompressionAlgorithmController
from nncf.api.compression import CompressionLevel
from nncf.algo_selector import COMPRESSION_ALGORITHMS
from nncf.compression_method_api import PTCompressionLoss
from nncf.utils import objwalk
from nncf.graph.transformations.layout import PTTransformationLayout


class KDLossCalculator(PTCompressionLoss):
    def __init__(self, original_model):
        super().__init__()
        self.original_model = original_model
        self.original_model.train()
        self.mse = torch.nn.MSELoss()

    def forward(self, input_=None, target=None):
        # input_ is compressed model output
        # target is input
        if input_ is None or target is None:
            raise ValueError('KDLoss entries cannot be None. Check compression loss arguments.')

        def is_loss(obj):
            if not isinstance(obj, torch.Tensor):
                return False
            if obj.requires_grad:
                return True
            return False

        def tensors_to_list(obj):
            if isinstance(obj, torch.Tensor):
                return [obj]
            else:
                return list(obj.values() if isinstance(obj, dict) else obj)
        ref_outputs = self.original_model(target)

        ref_loss_outputs = tensors_to_list(objwalk(ref_outputs, is_loss, lambda x: x))
        compressed_model_loss_outputs = tensors_to_list(objwalk(input_, is_loss, lambda x: x))
        return reduce(lambda kd_loss, loss_tensors: kd_loss + self.mse(loss_tensors[0], loss_tensors[1]),
                      zip(ref_loss_outputs, compressed_model_loss_outputs), 0)

    def statistics(self, quickly_collected_only=False):
        return {}


@COMPRESSION_ALGORITHMS.register('knowledge_distillation')
class KnowledgeDistillationBuilder(PTCompressionAlgorithmBuilder):
    def _apply_to(self, target_model):
        self.original_model = deepcopy(target_model.nncf_module)
        return []

    def build_controller(self, target_model):
        self.original_model = deepcopy(target_model.nncf_module)
        return KnowledgeDistillationController(target_model, self.original_model)

    def get_transformation_layout(self, model):
        return PTTransformationLayout()


class KnowledgeDistillationController(PTCompressionAlgorithmController):
    @property
    def loss(self) -> CompressionLoss:
        return self._loss

    @property
    def scheduler(self) -> CompressionScheduler:
        return self._scheduler

    def compression_level(self) -> CompressionLevel:
        return CompressionLevel.FULL

    def __init__(self, target_model, original_model):
        super().__init__(target_model)
        self._scheduler = BaseCompressionScheduler()
        self._loss = KDLossCalculator(original_model)

    def distributed(self):
        pass