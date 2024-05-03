import cProfile
import json
import os
import time
import urllib.parse

import boto3
import requests
import ts3

from botocore.exceptions import ClientError

from sqlalchemy import MetaData
from sqlalchemy import create_engine
from sqlalchemy import select, insert, update

from common.init_logging import setup_logger

# BEFORE YOU JUDGE THIS SCRIPT... I wrote it while drinking, i swear....
# Test Comment Here
# Total hours wasted on this script: 15 (as of 2024-01-23)
# Update: 2024-01-15: HOLY FUCK TREVOR!? WHY DO WE DO THE SAME THING TWICE IN DIFFERENT BLOCKS???
#                       YES it took me like 10 hours to realize that fact.

# Get the logger
logger = setup_logger(__name__)

# Get DEBUG environment variable
DEBUG = os.environ.get("DEBUG", False)

def get_secret():
    """
    Retrieves the database password from Secrets Manager.
    """
    secret_name = "prod/lambda/database_write"
    region_name = "us-east-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    # Parse the JSON string into a Python dictionary
    secret = json.loads(get_secret_value_response['SecretString'])

    db_user = secret['username']
    db_host = secret["host"]
    db_name = "nyartcco_nyartcc"
    db_pass = secret["password"]

    db_string = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}/{db_name}"

    logger.info(f"Database connection string: mysql+pymysql://{db_user}:***@{db_host}/{db_name}")

    return db_string




# Get the environment variables
tsUsername = os.environ["tsUsername"]
tsPass = os.environ["tsPass"]
tsHostname = os.environ["tsHostname"]

# Counters
# Count successful updates
updateCount = 0
# Count failed updates
failCount = 0

# TS3 Server Group IDs - This is the base group that is cloned to create each position group
sourceGroup = 227

# Database connection

db_string = get_secret()

engine = create_engine(db_string)
meta = MetaData(engine, reflect=True)
table = meta.tables["callsigns"]
table2 = meta.tables["online"]
table3 = meta.tables["controllers"]
ts_ids = meta.tables["ts_user"]
ts_MessageLog = meta.tables["ts_message_log"]


def incrementUpdateCount():
    """
    Increment the update count.
    """
    global updateCount
    updateCount += 1


def incrementFailCount():
    global failCount
    failCount += 1


class TimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutException("Timeout handler triggered!")


zny_web_instance = "https://nyartcc.org"


### PILOT BLOCK ###

def fetch_vatsim_pilots():
    """ Fetches active pilots from VATSIM data feed. """
    response = requests.get('http://data.vatsim.net/v3/vatsim-data.json')
    data = response.json()
    return {pilot['cid']: pilot for pilot in data['pilots']}

tracked_users = {
        '908962': 'kRhqR59V3/Ekbq1dpCr+QV8xAXo='
    }

def updatePilots(ts3conn, conn):
    """
    Update pilot groups in Teamspeak based on active pilots from VATSIM that are tracked.
    """
    active_pilots = fetch_vatsim_pilots()  # Fetches current active pilots

    # Fetch existing TS3 groups related to pilots
    ts3_groups = {group["name"]: int(group["sgid"]) for group in ts3conn.servergrouplist() if "Pilot_" in group["name"]}

    for cid, pilot in active_pilots.items():
        if cid in tracked_users:
            pilot_callsign = pilot['callsign']
            ts3uid = tracked_users[cid]
            group_name = f"Pilot_{pilot_callsign}"
            if group_name not in ts3_groups:
                # Create new group if not exists
                resp = ts3conn.servergroupcopy(ssgid=sourceGroup, tsgid=0, name=group_name, type_=1)
                ts3_groups[group_name] = int(resp.parsed[0]["sgid"])

            try:
                # Add the pilot to the respective group
                dbid = ts3conn.clientgetdbidfromuid(cluid=ts3uid).parsed[0]["cldbid"]
                ts3conn.servergroupaddclient(sgid=ts3_groups[group_name], cldbid=dbid)
                logger.info(f"Added pilot {cid} ({pilot_callsign}) to {group_name}")
                incrementUpdateCount()
            except Exception as e:
                logger.error(f"Failed to add/update pilot {cid} in TS3: {e}")
                incrementFailCount()
        else:
            logger.debug(f"Pilot {cid} not tracked. Skipping...")

    # Cleanup old pilot groups if no longer active
    for group_name, sgid in ts3_groups.items():
        if group_name not in [f"Pilot_{p['callsign']}" for p in active_pilots.values() if p['cid'] in tracked_users]:
            ts3conn.servergroupdel(sgid=sgid, force=1)
            logger.info(f"Deleted unused pilot group {group_name}")



### CONTROLLER BLOCK ###


def updatePos(ts3conn):
    """
    Update the positions of all online controllers.
    :param ts3conn:
    :return:
    """

    # List of all positions
    positions = []

    # Dictionary of all TS3 groups
    ts3_groups = {}

    # Dictionary of all online controllers
    onlineController = {}

    # Dictionary of all the users currently connected to the TS3 server
    trackedUsers = {}

    # Get the list of all online controllers from the ZNY website
    try:
        positionResponse = requests.get(zny_web_instance + '/api/positions/online')
        positionResponse.raise_for_status()  # Raises an error for 4xx or 5xx responses
        if not positionResponse.content:
            raise ValueError("Empty response received from positions API.")
        positionInfo = positionResponse.json()
    except requests.RequestException as e:
        logger.error(f"Request failed: {e}")
        raise
    except ValueError as e:
        logger.error(f"Invalid response: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response content: {positionResponse.text}")
        raise

    # Parse the list of online controllers
    for position in positionInfo['data']:

        # If the position is not in the dictionary of online controllers, add it
        if position['identifier'] not in onlineController:
            onlineController[position['identifier']] = []

        # Get the user info for the controller from the ZNY website
        try:
            user_info_response = requests.get(
                zny_web_instance + '/api/teamspeak/userIdentity?cid={}'.format(position['cid']))
            user_info_response.raise_for_status()
            if not user_info_response.content:
                raise ValueError("Empty response received from user info API.")
            userInfo = user_info_response.json()
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise
        except ValueError as e:
            logger.error(f"Invalid response: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response content: {user_info_response.text}")
            raise


        # Add the user to the position in the dictionary for that position
        for uid in userInfo:
            onlineController[position['identifier']].append(uid)

    # Connect to the database
    try:
        conn = engine.connect()
    except Exception as e:
        # Log the error with as much detail as possible
        logger.error(f"Database connection failed: {e}")

        # Sanitize the database URL before logging it
        sanitized_db_url = re.sub(r'//(.*):(.*)@', '//***:***@', str(db))

        # Log the sanitized database URL
        logger.error(f"Failed to connect to database at {sanitized_db_url}")

        # Raise the exception
        raise

    # Get the list of all positions from the database
    positionsAll = conn.execute(select([table])).fetchall()

    # Add all positions to the list of positions
    for position in positionsAll:
        positions.append(position["identifier"])

    # Get the list of all TS3 groups
    resp = ts3conn.servergrouplist()

    # Add all TS3 groups to the dictionary of groups
    for group in resp:
        ts3_groups[group["name"]] = int(group["sgid"])
    for group in ts3_groups:

        if group in positions and group not in onlineController:
            try:
                logger.info(f"Removing {group} from TS3 server group")
                ts3conn.servergroupdel(sgid=ts3_groups[group], force=1)
            except:
                pass

    for position in onlineController:
        trackedUsers[position] = []
        logger.info(f"Currently tracked users: {trackedUsers[position]}")
        time.sleep(.1)

        if position not in ts3_groups:
            resp = ts3conn.servergroupcopy(
                ssgid=sourceGroup, tsgid=0, name=position, type_=1
            )
            ts3_groups[position] = int(resp.parsed[0]["sgid"])
        for controller in onlineController[position]:
            logger.info(f"Current controller info: {controller}")
            resp = ts3conn.clientgetdbidfromuid(cluid=controller)
            dibUser = resp.parsed[0]["cldbid"]
            try:
                time.sleep(.1)
                logger.info(f"dibUser: {dibUser}")
                logger.info(f"Add {controller} to {position}")
                ts3conn.servergroupaddclient(
                    sgid=ts3_groups[position], cldbid=dibUser
                )
                incrementUpdateCount()
            except:
                logger.error(f"FAILED to add '{position}' to {controller}")
                incrementFailCount()
            finally:
                trackedUsers[position].append(dibUser)

        resp = ts3conn.servergroupclientlist(sgid=ts3_groups[position])

        for user in resp.parsed:
            logger.info(f"USER: {user}")

            if user["cldbid"] not in trackedUsers[position]:
                ts3conn.servergroupdelclient(
                    sgid=ts3_groups[position], cldbid=user["cldbid"]
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

    def sendMessageReg(client_unique_identifier, clid):
        """
        Send a message to a user to register on the ZNY website.
        :param client_unique_identifier: The client unique identifier from TS3.
        :param clid: The client ID from TS3.
        :return:
        """

        # give UID send message to user (DON'T RESEND FOR X TIME)
        # This works. Only issue is you Laravel cant accept a slash in Unicode and treats it as a
        # normal slash in the url.
        # Instead, we need to pass with a get param or within a post. I am
        # down for either, Post may be easier as it allows it to forward through.

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

        userInfo = ts3conn.clientinfo(clid=user["clid"])

        if userInfo.parsed[0]["client_unique_identifier"] in allTeamspeakIds:

            # Query the ZNY website API to get information about the user
            # Including CID, isStaff, isBoardMember, and other tags
            userInfoWebsite = requests.get(
                zny_web_instance + '/api/teamspeak/userinfo?uid={}'.format(
                    urllib.parse.quote_plus(userInfo.parsed[0]['client_unique_identifier']))).json()

            userGroupsTS = userInfo.parsed[0]['client_servergroups'].split(',')
            userGroupsTracked = list(set(groupsTracked) & set(userGroupsTS))
            userGroupsWebsite = userInfoWebsite['data']['tags']

            # FIXME: Here we should handle normal users and deal with position tags


            # Handle staff members
            # If user is a staff member, remove the 'NY Controller' tag - we're not supposed
            # to have both NY Controller and the Staff tag.
            if userInfoWebsite['data']['isStaff'] and '11' in userGroupsWebsite:
                userGroupsWebsite.remove('11')

            # If user is a board member, remove the 'NY Controller' tag and add the
            # 'Board Member' tag instead.
            if userInfoWebsite['data']['isBoardMember']:
                # Don't assign the "NY Controller" tag.
                logger.info("Found a board member!")
                logger.info(f"userInfoWebsite['data'] is currently: {userInfoWebsite['data']}")

                # Remove the 'NY Controller' tag
                if '11' in userGroupsWebsite:
                    logger.info("User has id 11 (NY Controller) in list. Removing it.")
                    try:
                        userGroupsWebsite.remove('11')
                    except error as e:
                        logger.error(f"Failed to remove tag 11. Error: {e}")
                    logger.info("Removed id 11 successfully!")

                # Add the 'Board Member' tag
                if '17401' in userGroupsWebsite:
                    userGroupsWebsite.append('17401')
                    logger.info(f"Successfully added id 17401 (Board Member) to user {userInfoWebsite['data']['cid']}")

                # Ignore server groups for 'KM'
                # Check if user is KM and if he has the 'I1' tag if so, remove it and add C3.
                if '73' in userGroupsWebsite and userInfoWebsite['data']['cid'] == 908962:
                    logger.info("Found user KM and he has id 73. He's a fake I1! Remove it!")
                    try:
                        userGroupsWebsite.remove('73')
                    except error as e:
                        logger.error(f"Failed to remove group 73. Error: {e}")
                        incrementFailCount()

                    userGroupsWebsite.append('72')
                    logger.info("Added group 72 instead.")
                    incrementUpdateCount()

            userAddGroups = list(set(userGroupsWebsite) - set(userGroupsTracked))
            userRemoveGroups = list(set(userGroupsTracked) - set(userGroupsWebsite))
            for groupId in userRemoveGroups:
                ts3conn.servergroupdelclient(sgid=groupId, cldbid=userInfo.parsed[0]['client_database_id'])
                incrementUpdateCount()
            for groupId in userAddGroups:
                ts3conn.servergroupaddclient(sgid=groupId, cldbid=userInfo.parsed[0]['client_database_id'])
                incrementUpdateCount()

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
                incrementUpdateCount()


def lambda_handler(event, context):
    """
    The main function that is executed by AWS Lambda when the function is triggered.
    :param event:
    :param context:
    :return:
    """

    try:
        with ts3.query.TS3Connection(tsHostname, "10011") as ts3conn:
            ts3conn.login(client_login_name=tsUsername, client_login_password=tsPass)
            ts3conn.use(sid=1)
            conn = engine.connect()
            updatePos(ts3conn)
            updateUsers(ts3conn, conn)
            updatePilots(ts3conn, conn)

        return {
            "statusCode": 200,
            "headers": {},
            "body": json.dumps({
                "message": f"Ran successfully! {updateCount} updates were made. {failCount} failed.",
            }),
        }
    except Exception as e:
        # Instead of returning, raise an exception to signal failure
        raise RuntimeError(f"Epic fail! {e}")
