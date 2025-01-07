from typing import List, Optional

from pydantic import BaseModel


class FileItem(BaseModel):
    name: str
    type: str
    path: str
    children: Optional[List['FileItem']] = None

class DirectoryListing(BaseModel):
    items: List[FileItem]

class FileContent(BaseModel):
    content: str