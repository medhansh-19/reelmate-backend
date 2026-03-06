from fastapi import APIRouter

router = APIRouter(
    prefix="/reel",
    tags=["reel"]
)

@router.get("/ping")
def ping():
    return {"message": "Reel router is working"}
