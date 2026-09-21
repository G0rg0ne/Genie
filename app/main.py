from fastapi import FastAPI
from utils.logger import  setup_logging
from api.routes import health,models,completions

setup_logging()

app = FastAPI()

app.include_router(health.router)
app.include_router(models.router)
app.include_router(completions.router)
