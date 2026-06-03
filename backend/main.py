from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {
        "message": "EcoGuard Agents API is running",
        "status": "success"
    }