from fastapi import FastAPI, HTTPException,Header
from fastapi.responses import HTMLResponse
from fastapi import Depends
from pydantic import BaseModel
from firebase_admin import credentials, firestore, initialize_app
import requests
from datetime import datetime
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
import jwt
from datetime import timedelta
import bcrypt

# Firebase Initialization
cred = credentials.Certificate("C:\\Users\\madha\\OneDrive\\Desktop\\health_records_app\\hospital-f2856-firebase-adminsdk-q3yr6-635eb65c61.json")
initialize_app(cred)
db = firestore.client()

# FastAPI App
app = FastAPI()

SECRET_KEY = "3c99f638181a85ca5601bb9e6a318be9de483c21c60bc49205981afa094a2ffd"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Create user model for registration and login
class LoginRequest(BaseModel):
    email: str
    password: str
# Models
class Hospital(BaseModel):
    name: str
    address: str
    contact: str = "N/A"

class Doctor(BaseModel):
    name: str
    specialization: str
    gender: str
    hospital_id: str  # Reference to hospital collection

class Appointment(BaseModel):
    doctor_id: str  # Doctor ID sent by the frontend
    date: str       # Date in ISO format (e.g., "2024-12-26")
    time: str     

class User(BaseModel):
    name: str
    email: str
    password: str 

class PatientData(BaseModel):
    patient_id: str
    data: dict
# Utility functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# User Registration
@app.post("/register")
async def register_user(user: User):
    try:
        # Hash the password
        hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Prepare user data
        user_data = user.dict()
        user_data["password"] = hashed_password  # Store hashed password

        # Save the user data to Firestore
        db.collection("users").add(user_data)

        return {"message": "User registered successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# User Login
@app.post("/login")
async def login_user(request: LoginRequest):
    try:
        # Fetch the user by email
        user_ref = db.collection("users").where("email", "==", request.email).get()

        if not user_ref:
            raise HTTPException(status_code=400, detail="Invalid email or password")

        user = user_ref[0].to_dict()  # Get the user data from Firestore
        stored_password = user["password"]  # Stored password (hashed)

        # Compare the hashed password with the user input password
        if not bcrypt.checkpw(request.password.encode('utf-8'), stored_password.encode('utf-8')):
            raise HTTPException(status_code=400, detail="Invalid email or password")

        # Generate JWT token for the user
        token_data = {"sub": user_ref[0].id}  # Store user_id in 'sub'
        token = create_access_token(data=token_data)

        # Return token and success message
        return {"message": "Login successful", "token": token}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/populate-dummy-data")
def populate_dummy_data():
    try:
        hospitals = [
            {"id": "HOSP1", "name": "General Hospital", "address": "123 Main St", "contact": "1234567890"},
            {"id": "HOSP2", "name": "City Care Hospital", "address": "456 Park Ave", "contact": "9876543210"},
        ]

        doctors = [
            {"name": "Dr. John Doe", "specialization": "Cardiology", "gender": "Male", "hospital_id": "HOSP1"},
            {"name": "Dr. Jane Smith", "specialization": "Neurology", "gender": "Female", "hospital_id": "HOSP2"},
        ]

        for hospital in hospitals:
            db.collection("hospitals").document(hospital["id"]).set(hospital)

        for doctor in doctors:
            db.collection("doctors").add(doctor)

        return {"message": "Dummy data populated successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# Hospitals
@app.get("/hospitals")
def get_hospitals():
    try:
        # Query all hospitals from the Firestore 'hospitals' collection
        hospitals_ref = db.collection("hospitals").stream()
        
        # Convert Firestore document snapshots to a list of hospital dictionaries
        hospitals = []
        for doc in hospitals_ref:
            hospital_data = doc.to_dict()
            hospital_data["hospital_id"] = doc.id  # Add document ID to the data
            hospitals.append(hospital_data)

        if not hospitals:
            return {"message": "No hospitals found", "hospitals": []}

        return {"message": "Hospitals retrieved successfully", "hospitals": hospitals}
    except Exception as e:
        # Log the error for debugging
        print(f"Error fetching hospitals: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch hospitals. Please try again later.")

# Doctors
@app.get("/doctors")
def get_doctors(hospital_id: str = None):
    try:
        doctors_ref = db.collection("doctors").stream()
        doctors = [
            {"doctor_id": doc.id, **doc.to_dict()}
            for doc in doctors_ref
            if not hospital_id or doc.to_dict().get("hospital_id") == hospital_id
        ]
        return doctors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Appointments
def get_current_user(authorization: str = Header(None)):
    if authorization is None:
        raise HTTPException(status_code=403, detail="Authorization header missing")

    try:
        # Check if the Authorization header is in the correct format
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=403, detail="Invalid Authorization header format")

        token = authorization.split(" ")[1]  # Extract the token part
        
        # Decode the JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")  # Assuming 'sub' contains the user_id

        if user_id is None:
            raise HTTPException(status_code=403, detail="Could not validate credentials")

        return user_id
    except JWTError:
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Invalid token: {str(e)}")
@app.post("/appointments")
def create_appointment(appointment: Appointment, user_id: str = Depends(get_current_user)):
    try:
        # Add user_id from JWT and created_at timestamp
        print(appointment.dict()) 
        new_appointment = appointment.dict()
        new_appointment["user_id"] = user_id  # Add the user_id from JWT
        new_appointment["created_at"] = datetime.utcnow().isoformat()  # Set the created_at timestamp

        # Save appointment to Firestore (or another database)
        appointment_ref = db.collection("appointments").add(new_appointment)  # Assuming Firestore as the DB
        return {
            "status": "success",
            "message": "Appointment booked successfully",
            "data": {"appointment_id": appointment_ref[1].id}  # Adjust according to your DB logic
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred while booking the appointment.")

# Map API for Nearby Hospitals
@app.get("/nearby_hospitals")
def get_nearby_hospitals(latitude: float, longitude: float):
    try:
        api_key = "AIzaSyAXwZjPuXKJaDRNBf3qGc_sTTz5P4qB-NA"
        radius = 5000  # 5 km radius
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={latitude},{longitude}&radius={radius}&type=hospital&key={api_key}"
        response = requests.get(url)
        data = response.json()

        nearby_hospitals = []
        for result in data.get("results", []):
            nearby_hospitals.append({
                "name": result["name"],
                "address": result["vicinity"],
                "location": result["geometry"]["location"]
            })
        
        return nearby_hospitals
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching nearby hospitals: {str(e)}")
@app.get("/", response_class=HTMLResponse)
async def get_home():
    with open("index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8515)
