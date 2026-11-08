from pydantic import BaseModel
from typing import List, Optional

class ProductMetaUpdate(BaseModel):
    description: Optional[str] = None
    marketing_name: Optional[str] = None
    images: Optional[List[str]] = None