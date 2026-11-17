from abc import ABC, abstractmethod
from typing import List
from autopsy.services.reconstruction_service import ExecutionGraph
from autopsy.detectors.finding import Finding


class BaseDetector(ABC):
    """
    Abstract base class for all independent failure detectors in Autopsy.
    """

    @property
    @abstractmethod
    def detector_name(self) -> str:
        """Returns unique identifier name for the detector."""
        pass

    @abstractmethod
    def detect(self, graph: ExecutionGraph) -> List[Finding]:
        """
        Scans an ExecutionGraph and returns observable findings.

        Args:
            graph: Reconstructed ExecutionGraph.

        Returns:
            List of Finding candidates supported by concrete evidence.
        """
        pass
