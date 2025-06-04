import os
import sys
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles  # ✅ NEW: for React static file serving
from pydantic import BaseModel
from openai import AzureOpenAI
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SimpleField, SearchableField, SearchFieldDataType
import pyotp
import qrcode
import io
import bcrypt
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

# ✅ Fail fast if required env vars are missing
REQUIRED_ENV_VARS = [
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_CONTAINER",
    "AZURE_FORM_RECOGNIZER_ENDPOINT",
    "AZURE_FORM_RECOGNIZER_KEY",
    "subscription_key",
    "endpoint",
    "AZURE_SEARCH_SERVICE_NAME",
    "AZURE_SEARCH_ADMIN_KEY",
    "AZURE_SEARCH_INDEX_NAME"
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

# ✅ FastAPI app init
app = FastAPI()

# ✅ Optional: Serve React static build (if applicable)
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

# ✅ CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check (important for Azure)
@app.get("/")
def health_check():
    return {"status": "ok"}

# Azure Table Storage
STORAGE_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
table_service_client = TableServiceClient.from_connection_string(STORAGE_CONN_STR)
table_client = table_service_client.get_table_client("Users")

try:
    table_client.create_table()
except Exception as e:
    if "TableAlreadyExists" not in str(e):
        print(f"⚠️ Table error: {e}")

# Seed demo users
def seed_users():
    users = [
        {
            "PartitionKey": "users",
            "RowKey": "alice",
            "PasswordHash": bcrypt.hashpw("secret123".encode(), bcrypt.gensalt()).decode(),
            "TwoFactorEnabled": True,
            "TwoFactorSecret": "JBSWY3DPEHPK3PXP",
        },
        {
            "PartitionKey": "users",
            "RowKey": "bob",
            "PasswordHash": bcrypt.hashpw("password".encode(), bcrypt.gensalt()).decode(),
            "TwoFactorEnabled": False,
            "TwoFactorSecret": None,
        },
    ]
    for user in users:
        existing = list(table_client.query_entities(f"PartitionKey eq 'users' and RowKey eq '{user['RowKey']}'"))
        if not existing:
            table_client.create_entity(entity=user)

seed_users()

# Azure Blob Storage
blob_conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
blob_container = os.getenv("AZURE_STORAGE_CONTAINER")
blob_service_client = BlobServiceClient.from_connection_string(blob_conn_str)
container_client = blob_service_client.get_container_client(blob_container)

try:
    container_client.create_container()
except Exception as e:
    if "ContainerAlreadyExists" not in str(e):
        print(f"⚠️ Blob container error: {e}")

# Azure Form Recognizer
form_client = DocumentAnalysisClient(
    endpoint=os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"),
    credential=AzureKeyCredential(os.getenv("AZURE_FORM_RECOGNIZER_KEY"))
)

# Azure OpenAI
openai_client = AzureOpenAI(
    api_key=os.getenv("subscription_key"),
    azure_endpoint=os.getenv("endpoint"),
    api_version="2024-02-15-preview"
)
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Azure Cognitive Search
search_service_name = os.getenv("AZURE_SEARCH_SERVICE_NAME")
search_admin_key = os.getenv("AZURE_SEARCH_ADMIN_KEY")
search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")
search_endpoint = f"https://{search_service_name}.search.windows.net"
search_credential = AzureKeyCredential(search_admin_key)
search_client = SearchClient(endpoint=search_endpoint, index_name=search_index_name, credential=search_credential)
index_client = SearchIndexClient(endpoint=search_endpoint, credential=search_credential)

def create_search_index():
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="filename", type=SearchFieldDataType.String),
        SearchableField(name="text", type=SearchFieldDataType.String),
        SimpleField(name="uploaded_at", type=SearchFieldDataType.String)
    ]
    index = SearchIndex(name=search_index_name, fields=fields)

    try:
        existing = [idx.name for idx in index_client.list_indexes()]
        if search_index_name not in existing:
            index_client.create_index(index)
            print(f"✅ Created new index: {search_index_name}")
        else:
            print(f"ℹ️ Index already exists: {search_index_name}")
    except Exception as e:
        print(f"❌ Index creation failed: {e}")

create_search_index()

# Models
class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TwoFAVerifyRequest(BaseModel):
    username: str
    token: str

# Auth endpoints
@app.post("/register")
async def register(req: RegisterRequest):
    existing = list(table_client.query_entities(f"PartitionKey eq 'users' and RowKey eq '{req.username}'"))
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_pw = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    entity = {
        "PartitionKey": "users",
        "RowKey": req.username,
        "PasswordHash": hashed_pw,
        "TwoFactorEnabled": False,
        "TwoFactorSecret": None
    }
    table_client.create_entity(entity=entity)
    return {"message": f"User '{req.username}' registered successfully"}

@app.post("/login")
async def login(req: LoginRequest):
    user = list(table_client.query_entities(f"PartitionKey eq 'users' and RowKey eq '{req.username}'"))
    if not user or not bcrypt.checkpw(req.password.encode(), user[0]["PasswordHash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user[0]["TwoFactorEnabled"]:
        return {"requires_2fa": True, "two_factor_enabled": True}
    return {"access_token": f"dummy_token_for_{req.username}", "two_factor_enabled": False}

@app.get("/2fa/setup")
async def setup_2fa(username: str):
    user = list(table_client.query_entities(f"PartitionKey eq 'users' and RowKey eq '{username}'"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    secret = pyotp.random_base32()
    user[0]["TwoFactorEnabled"] = True
    user[0]["TwoFactorSecret"] = secret
    table_client.update_entity(user[0])
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="RFPAnalyzerApp")
    qr = qrcode.make(uri)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/2fa/verify")
async def verify_2fa(req: TwoFAVerifyRequest):
    user = list(table_client.query_entities(f"PartitionKey eq 'users' and RowKey eq '{req.username}'"))
    if not user or not user[0]["TwoFactorEnabled"]:
        raise HTTPException(status_code=400, detail="2FA not enabled or user not found")
    totp = pyotp.TOTP(user[0]["TwoFactorSecret"])
    if not totp.verify(req.token):
        raise HTTPException(status_code=401, detail="Invalid 2FA token")
    return {"access_token": f"dummy_token_for_{req.username}"}

# Upload + Process endpoint
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        blob_client = container_client.get_blob_client(file.filename)
        contents = await file.read()
        blob_client.upload_blob(contents, overwrite=True)

        poller = form_client.begin_analyze_document("prebuilt-document", contents)
        result = poller.result()
        extracted_text = "\n".join([line.content for page in result.pages for line in page.lines])

        doc_id = str(uuid4())
        document = {
            "id": doc_id,
            "filename": file.filename,
            "text": extracted_text,
            "uploaded_at": datetime.utcnow().isoformat()
        }
        upload_result = search_client.upload_documents(documents=[document])
        if not upload_result[0].succeeded:
            raise Exception(f"Indexing failed: {upload_result[0].error_message}")

        return {"message": "File uploaded, processed, and indexed successfully."}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Upload or extraction failed: {str(e)}"})

# Chat endpoint
@app.post("/chat")
async def chat(user_input: str = Form(...)):
    try:
        results = search_client.search(search_text=user_input, top=3)
        relevant_docs = []
        references = set()

        for doc in results:
            text = doc.get("text", "")
            filename = doc.get("filename", "unknown")
            if text:
                relevant_docs.append(text)
                references.add(filename)

        if not relevant_docs:
            return JSONResponse(status_code=404, content={"error": "No relevant content found."})

        context_text = "\n\n".join(relevant_docs)
        sources = "\n".join(f"- {ref}" for ref in references)
        system_prompt = f"""
You are an intelligent assistant helping analyze RFP documents.

Use the following context extracted from past RFP documents to answer the user question.

Context:
{context_text}

Sources:
{sources}

Respond in markdown format with clearly labeled sections such as Technology Requirements, Pain Points, and BOM Recommendation.
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        response = openai_client.chat.completions.create(
            model=deployment_name,
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )

        return {"response": response.choices[0].message.content}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Chat error: {str(e)}"})
