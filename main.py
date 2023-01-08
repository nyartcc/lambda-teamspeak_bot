import time
import ts3
import os
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy import MetaData
from sqlalchemy import select, and_, exists, insert, update
from sqlalchemy.sql import func
import urllib.parse
import requests

# BEFORE YOU JUDGE THIS SCRIPT... I wrote it while drinking, i swear....


def lambda_handler(event, context):
    db = os.environ["db4"]
    tsUsername = os.environ["tsUsername"]
    tsPass = os.environ["tsPass"]
    tsHostname = os.environ["tsHostname"]
   
 
    sourceGroup = 227
    # sourceGroup = 4
   
    engine = create_engine(db)
    meta = MetaData(engine, reflect=True)
    table = meta.tables["callsigns"]
    table2 = meta.tables["online"]
    table3 = meta.tables["controllers"]
    ts_ids = meta.tables["ts_user"]
    ts_MessageLog = meta.tables["ts_message_log"]

    def updatePos(ts3conn):
        positions = []
        groups = {}
        onlineController = {}
        trackedUsers = {}

        positionInfo = requests.get('http://172.31.83.90/api/positions/online').json()
        for position in positionInfo['data']:
            if position['identifier'] not in onlineController:
                 onlineController[position['identifier']]=[]
            userInfo = requests.get('http://172.31.83.90/api/teamspeak/userIdentity?cid={}'.format(position['cid'])).json()
            for uid in userInfo:
                onlineController[position['identifier']].append(uid)


        conn = engine.connect()
        positionsAll = conn.execute(select([table])).fetchall()
        for position in positionsAll:
            positions.append(position["identifier"])
        resp = ts3conn.servergrouplist()
        for group in resp:
            groups[group["name"]] = int(group["sgid"])
        for group in groups:

            if group in positions and group not in onlineController:
                try:
                    print('del ' + group)
                    ts3conn.servergroupdel(sgid=groups[group], force=1)
                except:
                    pass

        for position in onlineController:
            trackedUsers[position]=[]
            print(trackedUsers[position])
            time.sleep(.1)
            # print(position)
            if position not in groups:
                resp = ts3conn.servergroupcopy(
                    ssgid=sourceGroup, tsgid=0, name=position, type_=1
                )
                groups[position] = int(resp.parsed[0]["sgid"])
            for controller in onlineController[position]:
                print(controller)
                resp = ts3conn.clientgetdbidfromuid(cluid=controller)
                dibUser = resp.parsed[0]["cldbid"]
                try:
                    time.sleep(.1)
                    print(dibUser)
                    print("add " + controller + " to " + position)
                    ts3conn.servergroupaddclient(
                        sgid=groups[position], cldbid=dibUser
                    )
                except:
                    print("FAILED add " + controller + " to " + position)
                finally:
                    trackedUsers[position].append(dibUser)

            resp = ts3conn.servergroupclientlist(sgid=groups[position])
            # print('CHECK REMOVE')
            for user in resp.parsed:
                print(user)
                # print(resp.parsed[0]['name'][-4:])
                # print(onlineController[position])
                if user["cldbid"] not in trackedUsers[position]:
                    ts3conn.servergroupdelclient(
                        sgid=groups[position], cldbid=resp.parsed[0]["cldbid"]
                    )
        print(groups)

    def updateUsers():
        def sendMessageReg(client_unique_identifier, clid):
            # give UID send mmessage to user (DONT RESEND FOR X TIME)
            # This works. Only issue is you Laraval cant accept a slash in Unicode and treats it as a normal slash in the url. Instead we need to pass with a get param or within a post. I am down for either, Post may be easier as it allows it to forward through.
            ts3conn.sendtextmessage(
                targetmode=1,
                target=clid,
                msg="Your teamspeak account is not registered with NYARTCC. In order to update Your positions, ratings and ARTCC status please click here https://nyartcc.org/ts/reg/set?uidStringID={}".format(
                    urllib.parse.quote_plus(client_unique_identifier)
                ),
            )
            # print('send message')
            return

        def sendBadUsername():
            # give UID send mmessage to user (DONT RESEND FOR X TIME)
            pass

        # get all users in TS and retrun as resp
        # getAllActiveUsers select from TS users link to users via CID. Allows for multiple Idents
        def checkLastMessage(uid, messageType):
            dbuserInfo = conn.execute(
                select([ts_MessageLog]).where(ts_MessageLog.c.uid == uid)
            ).fetchone()
            if dbuserInfo:
                return dbuserInfo["time"]
            else:
                conn.execute(
                    insert(ts_MessageLog),
                    [
                        {"uid": uid, "type": messageType, "time": 0},
                    ],
                )
                return 0

        def updateLastMessage(uid, messageType, time):
            conn.execute(
                update(ts_MessageLog)
                .where(ts_MessageLog.c.uid == uid)
                .values(time=time)
            )
            return

        resp = ts3conn.clientlist()
        conn = engine.connect()
        rawTsIds = conn.execute(select([ts_ids])).fetchall()
        allTeamspeakIds = []
        for ts_id in rawTsIds:
            allTeamspeakIds.append(ts_id["uid"])
        artccInfo = requests.get('http://172.31.83.90/api/teamspeak/serverinfo').json()
        groupsTracked = artccInfo['data']['tagsTracked']
        for user in resp.parsed:
            userInfo = ts3conn.clientinfo(clid=user["clid"])
            # print( userInfo.parsed[0]['client_type'])
            if userInfo.parsed[0]["client_type"] != "0":
                pass
            # checkDB for user in by user prim key of UID which will link CID to user

            elif userInfo.parsed[0]["client_unique_identifier"] in allTeamspeakIds:
                userInfoWebsite = requests.get('http://172.31.83.90/api/teamspeak/userinfo?uid={}'.format(urllib.parse.quote_plus(userInfo.parsed[0]['client_unique_identifier']))).json()
                userGroupsTS = userInfo.parsed[0]['client_servergroups'].split(',')
                userGroupsTracked = list(set(groupsTracked) & set(userGroupsTS))
                userGroupsWebsite = userInfoWebsite['data']['tags']
                if userInfoWebsite['data']['isStaff']:
                    if '11' in userGroupsWebsite and userInfoWebsite['data']['cid'] != 1361295:
                        userGroupsWebsite.remove('11')
                        
                    # Yeah this shit broke the bot. SORRY 
                    if '73' in userGroupsWebsite and userInfoWebsite['data']['cid'] == 908962:
                        userGroupsWebsite.remove('73')
                        userGroupsWebsite.append('72')

                userAddGroups = list(set(userGroupsWebsite) - set(userGroupsTracked))
                userRemoveGroups = list(set(userGroupsTracked) - set(userGroupsWebsite))
                for groupId in userRemoveGroups:
                    ts3conn.servergroupdelclient(sgid=groupId, cldbid= userInfo.parsed[0]['client_database_id'])
                for groupId in userAddGroups:
                    ts3conn.servergroupaddclient(sgid=groupId, cldbid= userInfo.parsed[0]['client_database_id'])
                #check if user in rating group
                # check if user in rating group
                # check if user is guest of nyartcc and assign
                pass
            else:
                if checkLastMessage(
                    userInfo.parsed[0]["client_unique_identifier"], "reg"
                ) < int(userInfo.parsed[0]["client_lastconnected"]):
                    updateLastMessage(
                        userInfo.parsed[0]["client_unique_identifier"],
                        "reg",
                        int(userInfo.parsed[0]["client_lastconnected"]),
                    )
                    sendMessageReg(
                        userInfo.parsed[0]["client_unique_identifier"], user["clid"]
                    )
                pass
                # send link to user to register self

    with ts3.query.TS3Connection(tsHostname, "10011") as ts3conn:
        ts3conn.login(client_login_name=tsUsername, client_login_password=tsPass)
        ts3conn.use(sid=1)
        updatePos(ts3conn)
        updateUsers()


lambda_handler("event", "context")
