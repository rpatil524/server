import typing as t

from django.db import transaction
from django.db.models import QuerySet
from fastapi import APIRouter, Depends, status

from etebase_server.django import models
from etebase_server.myauth.models import UserType, get_typed_user_model

from ..db_hack import django_db_cleanup_decorator
from ..msgpack import MsgpackResponse, MsgpackRoute
from ..stoken_handler import filter_by_stoken_and_limit
from ..utils import PERMISSIONS_READ, PERMISSIONS_READWRITE, BaseModel, get_object_or_404, permission_responses
from .authentication import get_authenticated_user
from .collection import get_collection, verify_collection_admin

User = get_typed_user_model()
member_router = APIRouter(route_class=MsgpackRoute, responses=permission_responses)
MemberQuerySet = QuerySet[models.CollectionMember]
default_queryset: MemberQuerySet = models.CollectionMember.objects.all()


@django_db_cleanup_decorator
def get_queryset(collection: models.Collection = Depends(get_collection)) -> MemberQuerySet:
    return default_queryset.filter(collection=collection)


@django_db_cleanup_decorator
def get_member(username: str, queryset: MemberQuerySet = Depends(get_queryset)) -> models.CollectionMember:
    return get_object_or_404(queryset, user__username__iexact=username)


class CollectionMemberModifyAccessLevelIn(BaseModel):
    accessLevel: models.AccessLevels


class CollectionMemberOut(BaseModel):
    username: str
    accessLevel: models.AccessLevels

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls: t.Type["CollectionMemberOut"], obj: models.CollectionMember) -> "CollectionMemberOut":
        return cls(username=obj.user.username, accessLevel=obj.accessLevel)


class MemberListResponse(BaseModel):
    data: t.List[CollectionMemberOut]
    iterator: t.Optional[str] = None
    done: bool


@member_router.get(
    "/member/", response_model=MemberListResponse, dependencies=[Depends(verify_collection_admin), *PERMISSIONS_READ]
)
def member_list(
    iterator: t.Optional[str] = None,
    limit: int = 50,
    queryset: MemberQuerySet = Depends(get_queryset),
):
    queryset = queryset.order_by("id")
    result, new_stoken_obj, done = filter_by_stoken_and_limit(
        iterator, limit, queryset, models.CollectionMember.stoken_annotation
    )
    new_stoken = new_stoken_obj and new_stoken_obj.uid

    return MsgpackResponse(
        MemberListResponse(
            data=[CollectionMemberOut.from_orm(item) for item in result],
            iterator=new_stoken,
            done=done,
        )
    )


@member_router.delete(
    "/member/{username}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_collection_admin), *PERMISSIONS_READWRITE],
)
def member_delete(
    obj: models.CollectionMember = Depends(get_member),
):
    obj.revoke()


@member_router.patch(
    "/member/{username}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_collection_admin), *PERMISSIONS_READWRITE],
)
def member_patch(
    data: CollectionMemberModifyAccessLevelIn,
    instance: models.CollectionMember = Depends(get_member),
):
    with transaction.atomic():
        # We only allow updating accessLevel
        if instance.accessLevel != data.accessLevel:
            instance.stoken = models.Stoken.objects.create()
            instance.accessLevel = data.accessLevel
            instance.save()


@member_router.post("/member/leave/", status_code=status.HTTP_204_NO_CONTENT, dependencies=PERMISSIONS_READ)
def member_leave(
    user: UserType = Depends(get_authenticated_user), collection: models.Collection = Depends(get_collection)
):
    obj = get_object_or_404(collection.members, user=user)
    obj.revoke()
