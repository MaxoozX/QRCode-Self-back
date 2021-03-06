import asyncio
from uuid import uuid4, UUID

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio

# Imports locaux
import error_messages as ERROR
from const import MAX_TABLE_SIZE, SHEET_ID, SHEET_NAME, GOOGLE_APPLICATION_CREDENTIALS

from GoogleSheetTableLogger import GoogleSheetTableLogger
from schemas import TableMember, ClassicResponseModel, TableMembersModel, SettleTableModel
from dependencies import isValidName, getCurrentTime, compute_query_string, UUIDEncoder

#----------------------------------------------------------#
# Gestion des données

tables = {} # TODO: Il faudra utiliser une base de donnée plutot qu'un simple dict

table_logger = GoogleSheetTableLogger(GOOGLE_APPLICATION_CREDENTIALS, SHEET_ID, SHEET_NAME)

#----------------------------------------------------------#

app = FastAPI()

# Régler les problèmes de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*'
)

# La partie socketio

async def notify_change(room_ID: UUID) -> None:

    asyncio.get_event_loop().create_task(sio.emit(
        "table_update",
        {
            "members": tables[room_ID]
        },
        room=str(room_ID)
    ))
    return

@sio.on("connect")
async def handle_connect(sid, environ, auth):
    query = compute_query_string(environ["QUERY_STRING"])
    room_ID = query["room_id"]
    if not room_ID or room_ID == "undefined":
        return False

    sio.enter_room(sid, room_ID)

    return "OK"

# La partie API

@app.get("/")
async def root():
    return {"message": "Coucou le LP"}


@app.post("/create-table")
async def create_table_route() -> dict:
    """Create a room in the database"""

    new_table_ID = uuid4()
    while new_table_ID in tables.keys():
        new_table_ID = uuid4()

    tables[new_table_ID] = []
    return {"status": "ok", "table-ID": new_table_ID,}


@app.put("/add-member", response_model=ClassicResponseModel)
async def add_member_route(member: TableMember, tableid: UUID):
    """Add a member to a room"""

    firstname = str(member.firstname)
    lastname = str(member.lastname)
    classID = str(member.classID)

    if tableid not in tables.keys():
        return JSONResponse(
            status_code=404,
            content={
                "status": "table not found",
                "message": ERROR.TABLE_NOT_FOUND
            }
        )

    cur_table = tables[tableid]

    if not isValidName(firstname):
        return JSONResponse(
            status_code=417,
            content={
                "status": "invalid firstname",
                "message": ERROR.INVALID_FIRSTNAME
            }
        )
    if not isValidName(lastname):
        return JSONResponse(
            status_code=417,
            content={
                "status": "invalid firstname",
                "message": ERROR.INVALID_LASTNAME
            }
        )

    # check that the table is not full
    if len(cur_table) >= MAX_TABLE_SIZE:
        return JSONResponse(
            status_code=409,
            content={
                "status": "table full",
                "message": ERROR.TABLE_FULL
            }
        )

    # check the person isn't already in the table
    for member in cur_table:
        if member["firstname"] == firstname and member["lastname"] == lastname:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "user already in the table",
                    "message": ERROR.MEMBER_ALREADY_EXISTS
                }
            )

    cur_table.append({
        "ID": str(uuid4()),
        "time": getCurrentTime(),
        "firstname": firstname,
        "lastname": lastname,
        "classID": classID,
    })

    await notify_change(tableid)

    return {"status": "ok"}

@app.delete("/remove-member", response_model=ClassicResponseModel)
async def remove_member_route(tableid: UUID, memberid: UUID):

    if tableid not in tables.keys():
        return JSONResponse(
            status_code=404,
            content={
                "status": "table not found",
                "message": ERROR.TABLE_NOT_FOUND
            }
        )

    memberid = str(memberid)
    cur_table = tables[tableid]

    for idx, el in enumerate(cur_table):
        if el["ID"] == memberid:
            print(el)
            cur_table.pop(idx)
            break
    else :
        return JSONResponse(
            status_code=404,
            content={
                "status": "member not found",
                "message": ERROR.USER_NOT_FOUND
            }
        )

    await notify_change(tableid)

    return {"status": "ok"}

@app.get("/table-info", response_model=TableMembersModel, responses={404: {"model": ClassicResponseModel}})
async def table_info_route(tableid: UUID):

    if tableid not in tables.keys():
        return JSONResponse(
            status_code=404,
            content={
                "status": "table not found",
                "message": ERROR.TABLE_NOT_FOUND
            }
        )

    return tables[tableid]


# How is called this endpoint ??
@app.put("/settle-table")
async def settle_table_route(tableid: UUID, body: SettleTableModel):

    location = str(body.location)

    if tableid not in tables.keys():
        return JSONResponse(
            status_code=404,
            content={
                "status": "table not found",
                "message": ERROR.TABLE_NOT_FOUND
            }
        )

    if not location:
        return JSONResponse(
            status_code=417,
            content={
                "status": "wrong table location",
                "message": ERROR.WRONG_TABLE_LOCATION
            }
        )

    cur_table = tables[tableid]

    # Check the table is ready. FIXME: There will be special cases that must taken care of 
    if len(cur_table) < MAX_TABLE_SIZE:
        return JSONResponse(
            status_code=417,
            content={
                "status": "table full",
                "message": ERROR.TABLE_NOT_FULL
            }
        )

    cur_time = getCurrentTime()
    for member in cur_table:
        member["table"] = location
        member["time"] = cur_time

    if not table_logger(cur_table):
        
        return JSONResponse(
            status_code=500,
            content={
                "status": "impossible to save table",
                "message": ERROR.TABLE_COULDNT_BE_SAVED
            }
        )

    del tables[tableid]

    return {"status": "ok"}

app = socketio.ASGIApp(sio, other_asgi_app=app)

# TODO:

# - Scripts to setup the backend (Docker ?)

# - Use SQLite instead of a simple dict

# - Pushing to github
# - Deploying
