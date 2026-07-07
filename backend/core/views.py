from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        db_ok = cursor.fetchone()[0] == 1
    return Response(
        {
            "status": "ok",
            "db": "ok" if db_ok else "error",
            "engine": connection.vendor,
        }
    )
