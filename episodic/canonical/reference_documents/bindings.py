

async def list_reference_bindings_paged(
    uow: CanonicalUnitOfWork,
    *,
    request: ReferenceBindingListRequest,
) -> tuple[list[ReferenceBinding], int]:
    """List reusable reference bindings and their unpaginated total."""
    _validate_pagination(request.limit, request.offset)
    parsed_target_kind = _parse_target_kind(request.target_kind)
    parsed_target_id = _parse_uuid(request.target_id, "target_id")
    bindings = await uow.reference_bindings.list_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
        limit=request.limit,
        offset=request.offset,
    )
    total = await uow.reference_bindings.count_for_target(
        target_kind=parsed_target_kind,
        target_id=parsed_target_id,
    )
    return bindings, total
