"""
License status route (on-premises only).

GET /license/status — returns the current license state.

This endpoint is only available when S2S_DEPLOY_MODE=onprem.
In SaaS mode it returns 404 to avoid leaking deployment details.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from services.license import LicenseError, get_license_status, is_deploy_mode_onprem

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/status",
    summary="License status",
    description=(
        "Returns the on-premises license state: plan, customer, seat counts, "
        "expiry, and enabled features. Only available when S2S_DEPLOY_MODE=onprem."
    ),
)
async def license_status() -> dict[str, Any]:
    if not is_deploy_mode_onprem():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License endpoint is only available for on-premises deployments.",
        )

    try:
        return get_license_status()
    except LicenseError as exc:
        logger.error("License status check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code":        "license_invalid",
                "message":     str(exc),
                "upgrade_url": "https://stream2stack.com/on-prem",
            },
        )
