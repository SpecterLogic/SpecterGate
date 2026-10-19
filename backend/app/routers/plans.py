from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip, require_permission
from app.models import Admin, Plan
from app.schemas import OperationResult, PlanCreate, PlanOut, PlanUpdate
from app.services.audit import write_audit


router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db), _: Admin = Depends(require_permission("plans.read"))):
    return db.query(Plan).order_by(Plan.is_active.desc(), Plan.price.asc()).all()


@router.post("", response_model=PlanOut, status_code=201)
def create_plan(
    payload: PlanCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(require_permission("plans.manage")),
):
    if db.query(Plan).filter(Plan.name == payload.name).first():
        raise HTTPException(status_code=409, detail="این نام پلن قبلاً ثبت شده است.")
    plan = Plan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    write_audit(
        db, actor, "create_plan", "plan", plan.id, f"ایجاد پلن {plan.name}", get_client_ip(request)
    )
    return plan


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: int,
    payload: PlanUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(require_permission("plans.manage")),
):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="پلن پیدا نشد.")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != plan.name:
        if db.query(Plan).filter(Plan.name == data["name"]).first():
            raise HTTPException(status_code=409, detail="این نام پلن قبلاً ثبت شده است.")
    for key, value in data.items():
        setattr(plan, key, value)
    db.commit()
    db.refresh(plan)
    write_audit(
        db, actor, "update_plan", "plan", plan.id, f"ویرایش پلن {plan.name}", get_client_ip(request)
    )
    return plan


@router.delete("/{plan_id}", response_model=OperationResult)
def delete_plan(
    plan_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: Admin = Depends(require_permission("plans.manage")),
):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="پلن پیدا نشد.")
    name = plan.name
    db.delete(plan)
    db.commit()
    write_audit(
        db, actor, "delete_plan", "plan", plan_id, f"حذف پلن {name}", get_client_ip(request)
    )
    return OperationResult(ok=True, message="پلن حذف شد.")
