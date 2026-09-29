from fastapi import FastAPI
import sys
from starlette.middleware.cors import CORSMiddleware
from controller.Admin_Controller import router as admin_router
from controller.List_Controller import router as List_router
# from controller.Client_Controller import router as client_router
# from controller.Kyc_Controller import router as kyc_router
# from controller.Auth_Controller import router as auth_router
from local.Middlewares.middleware import log_request
from local.lifespan import lifespan
# from fastapi_session import FastAPISessionMiddleware


sys.path.append('.')
sys.path.append('../')

app = FastAPI(title="Project Management",lifespan=lifespan)

app.middleware("http")(log_request)

# app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(List_router)
# app.include_router(client_router)
# app.include_router(kyc_router)


app.add_middleware(
    CORSMiddleware,

    allow_origins=['*'],
    # allow_origins=[r"http://localhost:3000",
    #                r"http://localhost:3001",
    #                r"http://localhost:3002"],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*']
)
