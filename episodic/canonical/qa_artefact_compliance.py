"""The compliance policy that turns Pedante findings into a verdict.

The policy is deliberately a single predicate. It reads the support level of
each finding and nothing else, so an advisory finding can never hold an episode
back and a severity change cannot silently move an artefact's verdict.
"""

import typing as typ

from .qa_artefacts import QaComplianceStatus

if typ.TYPE_CHECKING:
    from episodic.qa.pedante.types import PedanteEvaluationResult


def compliance_status_for_pedante(
    result: PedanteEvaluationResult,
) -> QaComplianceStatus:
    """Return the verdict Pedante's blocking policy gives a result.

    Parameters
    ----------
    result : PedanteEvaluationResult
        Typed Pedante findings for one script.

    Returns
    -------
    QaComplianceStatus
        ``NON_COMPLIANT`` when any finding blocks editorial approval, and
        ``COMPLIANT`` otherwise. Severity does not decide the verdict; the
        support level does, so an advisory finding never holds an episode back.
    """
    if result.requires_revision:
        return QaComplianceStatus.NON_COMPLIANT
    return QaComplianceStatus.COMPLIANT
