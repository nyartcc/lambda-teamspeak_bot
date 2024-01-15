import cProfile
import json
import os
import signal
import time
import urllib.parse

import boto3
import requests
import ts3

from sqlalchemy import MetaData
from sqlalchemy import create_engine
from sqlalchemy import select, insert, update

from common.init_logging import setup_logger

# BEFORE YOU JUDGE THIS SCRIPT... I wrote it while drinking, i swear....
# Test Comment Here
# Total hours wasted on this script: 10 (as of 2023-12-10)

# Get the logger
logger = setup_logger(__name__)

# Get DEBUG environment variable
DEBUG = os.environ.get("DEBUG", False)

# Get the environment variables
db = os.environ["db4"]
tsUsername = os.environ["tsUsername"]
tsPass = os.environ["tsPass"]
tsHostname = os.environ["tsHostname"]

# Counters
# Count successful updates
updateCount = 0
# Count failed updates
failCount = 0

# TS3 Server Group IDs - Trevor needs to explain this to me
sourceGroup = 227
# sourceGroup = 4

# Database connection
engine = create_engine(db)
meta = MetaData(engine, reflect=True)
table = meta.tables["callsigns"]
table2 = meta.tables["online"]
table3 = meta.tables["controllers"]
ts_ids = meta.tables["ts_user"]
ts_MessageLog = meta.tables["ts_message_log"]


def incrementUpdateCount():
    global updateCount
    updateCount += 1


def incrementFailCount():
    global failCount
    failCount += 1


class TimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutException("Timeout handler triggered!")


# signal.signal(signal.SIGALRM, timeout_handler)


zny_web_instance = "https://nyartcc.org"


def updatePos(ts3conn, conn):
    """
    Update the positions of all online controllers.
    :param ts3conn:
    :return:
    """

    # List of all positions
    positions = []

    # Dictionary of all TS3 groups
    groups = {}

    # Dictionary of all online controllers
    onlineController = {}

    # Dictionary of all the users currently connected to the TS3 server
    trackedUsers = {}

    # Get the list of all online controllers from the ZNY website
    positionInfo = requests.get(zny_web_instance + '/api/positions/online').json()

    # Parse the list of online controllers
    for position in positionInfo['data']:

        # If the position is not in the dictionary of online controllers, add it
        if position['identifier'] not in onlineController:
            onlineController[position['identifier']] = []

        # Get the user info for the controller from the ZNY website
        userInfo = requests.get(
            zny_web_instance + '/api/teamspeak/userIdentity?cid={}'.format(position['cid'])).json()

        # Add the user to the position in the dictionary for that position
        for uid in userInfo:
            onlineController[position['identifier']].append(uid)

    # Connect to the database
    conn = engine.connect()

    # Get the list of all positions from the database
    positionsAll = conn.execute(select([table])).fetchall()

    # Add all positions to the list of positions
    for position in positionsAll:
        positions.append(position["identifier"])

    # Get the list of all TS3 groups
    resp = ts3conn.servergrouplist()

    # Add all TS3 groups to the dictionary of groups
    for group in resp:
        groups[group["name"]] = int(group["sgid"])
    for group in groups:

        if group in positions and group not in onlineController:
            try:
                logger.info(f"Removing {group} from TS3 server group")
                ts3conn.servergroupdel(sgid=groups[group], force=1)
            except:
                pass

    for position in onlineController:
        trackedUsers[position] = []
        logger.info(f"Currently tracked users: {trackedUsers[position]}")
        time.sleep(.1)

        if position not in groups:
            resp = ts3conn.servergroupcopy(
                ssgid=sourceGroup, tsgid=0, name=position, type_=1
            )
            groups[position] = int(resp.parsed[0]["sgid"])
        for controller in onlineController[position]:
            logger.info(f"Current controller info: {controller}")
            resp = ts3conn.clientgetdbidfromuid(cluid=controller)
            dibUser = resp.parsed[0]["cldbid"]
            try:
                time.sleep(.1)
                logger.info(f"dibUser: {dibUser}")
                logger.info(f"Add {controller} to {position}")
                ts3conn.servergroupaddclient(
                    sgid=groups[position], cldbid=dibUser
                )
                incrementUpdateCount()
            except:
                logger.error(f"FAILED to add {controller} to {position}")
                incrementFailCount()
            finally:
                trackedUsers[position].append(dibUser)

        resp = ts3conn.servergroupclientlist(sgid=groups[position])

        for user in resp.parsed:
            logger.info(f"USER: {user}")

            if user["cldbid"] not in trackedUsers[position]:
                ts3conn.servergroupdelclient(
                    sgid=groups[position], cldbid=user["cldbid"]
                )
                incrementUpdateCount()
                logger.info(f"Removed {user['cldbid']} from {position}")


def updateUsers(ts3conn, conn):
    """
    Update the positions of all online controllers.
    :param ts3conn:  The TS3 connection.
    :param conn:   The database connection.
    :return:
    """

    conn = conn

    def sendMessageReg(client_unique_identifier, clid):
        """
        Send a message to a user to register on the ZNY website.
        :param client_unique_identifier: The client unique identifier from TS3.
        :param clid: The client ID from TS3.
        :return:
        """
        # give UID send mmessage to user (DONT RESEND FOR X TIME)
        # This works. Only issue is you Laraval cant accept a slash in Unicode and treats it as a normal slash in the url. Instead we need to pass with a get param or within a post. I am down for either, Post may be easier as it allows it to forward through.
        ts3conn.sendtextmessage(
            targetmode=1,
            target=clid,
            msg="Your teamspeak account is not registered with NYARTCC. In order to update Your positions, ratings and ARTCC status please click here https://nyartcc.org/ts/reg/set?uidStringID={}".format(
                urllib.parse.quote_plus(client_unique_identifier)
            ),
        )
        logger.debug(f"Sent welcome message to {clid}")

        return True

    def sendBadUsername():
        """
        Send a message to a user to change their username.
        :return:
        """
        # give UID send mmessage to user (DONT RESEND FOR X TIME)
        pass

        # get all users in TS and return as resp
        # getAllActiveUsers select from TS users link to users via CID. Allows for multiple Idents

    # get all users in TS and return as resp
    # getAllActiveUsers select from TS users link to users via CID. Allows for multiple Idents
    def checkLastMessage(uid, messageType):
        """
        Check the last message time for a user
        :param uid:
        :param messageType:
        :return:
        """
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
        """
        Update the last message time for a user
        :param uid:
        :param messageType:
        :param time:
        :return:
        """
        conn.execute(
            update(ts_MessageLog)
            .where(ts_MessageLog.c.uid == uid)
            .values(time=time)
        )
        return True

    resp = ts3conn.clientlist()

    rawTsIds = conn.execute(select([ts_ids])).fetchall()
    allTeamspeakIds = []
    for ts_id in rawTsIds:
        allTeamspeakIds.append(ts_id["uid"])

    artccInfo = requests.get(zny_web_instance + '/api/teamspeak/serverinfo').json()
    groupsTracked = artccInfo['data']['tagsTracked']

    for user in resp.parsed:
        logger.info(f"Variable USER is currently: {user}")
        if user["client_database_id"] == 1:
            pass
        userInfo = ts3conn.clientinfo(clid=user["clid"])

        if userInfo.parsed[0]["client_type"] != "0":
            pass

        elif userInfo.parsed[0]["client_unique_identifier"] in allTeamspeakIds:
            userInfoWebsite = requests.get(
                zny_web_instance + '/api/teamspeak/userinfo?uid={}'.format(
                    urllib.parse.quote_plus(userInfo.parsed[0]['client_unique_identifier']))).json()
            userGroupsTS = userInfo.parsed[0]['client_servergroups'].split(',')
            userGroupsTracked = list(set(groupsTracked) & set(userGroupsTS))
            userGroupsWebsite = userInfoWebsite['data']['tags']
            if userInfoWebsite['data']['isStaff']:
                if '11' in userGroupsWebsite:
                    userGroupsWebsite.remove('11')

            # If user is a board member
            if userInfoWebsite['data']['isBoardMember']:
                # Don't assign the "NY Controller" tag.
                logger.info(f"Found a board member!")
                logger.info(f"userInfoWebsite['data'] is currently: {userInfoWebsite['data']}")

                if '11' in userGroupsWebsite:
                    logger.info(f"User has id 11 in list. Removing it.")
                    try:
                        userGroupsWebsite.remove('11')
                    except error as e:
                        logger.info(f"Failed to remove tag 11. Error: {e}")
                    logger.info("Removed id 11 successfully!")

                # Add the 'Board Member' tag
                userGroupsWebsite.append('17401')
                logger.info(f"Sucessfully added id 17401 to user {userInfoWebsite['data']['cid']}")

                # Ignore server groups for 'KM'
                # Check if user is KM and if he has the 'I1' tag if so, remove it and add C3.
                if '73' in userGroupsWebsite and userInfoWebsite['data']['cid'] == 908962:
                    logger.info(f"Found user KM and he has id 73. He's a fake I1! Remove it!")
                    try:
                        userGroupsWebsite.remove('73')
                    except error as e:
                        logger.info(f"Failed to remove group 73. Error: {e}")

                    userGroupsWebsite.append('72')
                    logger.info(f"Added group 72 instead.")

            userAddGroups = list(set(userGroupsWebsite) - set(userGroupsTracked))
            userRemoveGroups = list(set(userGroupsTracked) - set(userGroupsWebsite))
            for groupId in userRemoveGroups:
                ts3conn.servergroupdelclient(sgid=groupId, cldbid=userInfo.parsed[0]['client_database_id'])
                incrementUpdateCount()
            for groupId in userAddGroups:
                ts3conn.servergroupaddclient(sgid=groupId, cldbid=userInfo.parsed[0]['client_database_id'])
                incrementUpdateCount()
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


def lambda_handler(event, context):
    """
    The main function that is executed by AWS Lambda when the function is triggered.
    :param event:
    :param context:
    :return:
    """
    # profiler = cProfile.Profile()
    # profiler.enable()

    # Get the IP address of the ZNY-Website-Production EC2 instance
    # zny_web_instance_ip = ZNY_WEB_SERVER_IP
    signal.alarm(15)

    with ts3.query.TS3Connection(tsHostname, "10011") as ts3conn:
        ts3conn.login(client_login_name=tsUsername, client_login_password=tsPass)
        ts3conn.use(sid=1)
        conn = engine.connect()
        updatePos(ts3conn, conn)
        updateUsers(ts3conn, conn)

    return {
        "statusCode": 200,
        "headers": {},
        "body": json.dumps({
            "message": f"Ran successfully! {updateCount} updates were made. {failCount} failed.",
        }),
    }
