def get_client_ip(request) -> str:
    """X-Forwarded-For najpierw — w produkcji stoimy za proxy/load
    balancerem, więc REMOTE_ADDR wskazywałby na niego, nie na klienta."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
