from fastapi import FastAPI
from utils.logger import  setup_logging
from api.routes import health

setup_logging()

app = FastAPI()

app.include_router(health.router)
