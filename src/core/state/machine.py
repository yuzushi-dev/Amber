"""
Document State Machine
======================

Defines the valid states and transitions for document processing.
"""

from enum import Enum


class DocumentStatus(str, Enum):
    """Enumeration of valid document processing states."""

    INGESTED = "ingested"
    EXTRACTING = "extracting"
    CLASSIFYING = "classifying"
    CHUNKING = "chunking"
    READY = "ready"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"  # Added for quality gate logic


class InvalidTransitionError(Exception):
    """Exception raised when an invalid state transition is attempted."""

    def __init__(self, current_status: DocumentStatus, new_status: DocumentStatus):
        self.current_status = current_status
        self.new_status = new_status
        super().__init__(
            f"Invalid transition from {current_status.value} to {new_status.value}"
        )


class TransitionManager:
    """Manages valid state transitions for documents."""

    # Define valid transitions: key = current state, value = set of valid next states
    _VALID_TRANSITIONS = {
        DocumentStatus.INGESTED: {DocumentStatus.EXTRACTING, DocumentStatus.FAILED},
        DocumentStatus.EXTRACTING: {
            DocumentStatus.CLASSIFYING,
            DocumentStatus.FAILED,
            DocumentStatus.NEEDS_REVIEW,
        },
        DocumentStatus.NEEDS_REVIEW: {
            DocumentStatus.EXTRACTING,  # Retry/Force
            DocumentStatus.FAILED,
            DocumentStatus.CLASSIFYING,  # Approve
        },
        DocumentStatus.CLASSIFYING: {
            DocumentStatus.CHUNKING,
            DocumentStatus.FAILED,
        },
        DocumentStatus.CHUNKING: {
            DocumentStatus.READY,
            DocumentStatus.FAILED,
        },
        DocumentStatus.READY: {
            DocumentStatus.INGESTED,  # Allow re-ingestion/reset
            DocumentStatus.EXTRACTING, # Allow re-processing
        },
        DocumentStatus.FAILED: {
            DocumentStatus.INGESTED,  # Retry from scratch
            DocumentStatus.EXTRACTING, # Retry step
        },
    }

    @classmethod
    def validate_transition(
        cls, current_status: DocumentStatus, new_status: DocumentStatus
    ) -> None:
        """
        Validate if a transition is allowed.

        Args:
            current_status: Current state of the document
            new_status: Target state

        Raises:
            InvalidTransitionError: If the transition is not allowed
        """
        # Allow transition to self (no-op)
        if current_status == new_status:
            return

        allowed_next_states = cls._VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_next_states:
            raise InvalidTransitionError(current_status, new_status)
