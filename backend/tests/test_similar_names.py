"""Deteccion de nombres desalineados entre equipos.

Es la parte del valor del pasamanos que no depende de conocer negocio: con 9
equipos nombrando eventos por su cuenta, los typos y las variantes son la falla
de integracion mas comun y la mas difícil de ver a ojo.
"""

from __future__ import annotations

import pytest

from app.services.stats_service import _is_near_duplicate, _split_camel


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Casos reales del board de Miro.
        ("debtOverdue", "overdueDebt"),
        ("streetClosureEnded", "streetClousureEnded"),
        ("environmentalInspectionScheduled", "enviromentalInspectionScheduled"),
        ("environmentalViolationDetected", "envirometnalViolationDetected"),
    ],
)
def test_detecta_desalineaciones_reales(left, right):
    assert _is_near_duplicate(left, right)
    assert _is_near_duplicate(right, left), "tiene que ser simetrico"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Eventos genuinamente distintos: no deben marcarse.
        ("ticketCreated", "ticketUpdated"),
        ("paymentRegistered", "paymentReversed"),
        ("workOrderScheduled", "workOrderCompleted"),
        ("citizenBlocked", "citizenDeceased"),
        ("exemptionApproved", "exemptionRejected"),
        ("urbanServiceStarted", "urbanServiceDelayed"),
    ],
)
def test_no_marca_eventos_distintos(left, right):
    assert not _is_near_duplicate(left, right)


def test_un_nombre_no_es_duplicado_de_si_mismo():
    assert not _is_near_duplicate("ticketCreated", "ticketCreated")


def test_no_marca_nombres_cortos():
    """En nombres cortos una letra de diferencia suele ser intencional."""
    assert not _is_near_duplicate("ack", "nack")


def test_parte_camel_case():
    assert _split_camel("debtOverdue") == ["debt", "overdue"]
    assert _split_camel("streetClosureEnded") == ["street", "closure", "ended"]
    assert _split_camel("ticket") == ["ticket"]
