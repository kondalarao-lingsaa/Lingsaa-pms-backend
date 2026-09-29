import logging
from fastapi import Request
import time
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware

access_logger  = logging.getLogger('access')
async def log_request(request:Request,call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    access_logger.info(
        {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "process_time": process_time,
            "status_code": response.status_code,
        }
    )
    return response

