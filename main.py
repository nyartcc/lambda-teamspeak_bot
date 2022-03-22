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


# BEFORE YOU JUDGE THIS SCRIPT... I wrote it while drinking, i swear....

def lambda_handler(event, context):
    db = os.environ['db4']
    tsUsername = os.environ['tsUsername']
    tsPass = os.environ['tsPass']
    tsHostname = os.environ['tsHostname']
    groups={}
    positions=[]
    sourceGroup = 227
    #sourceGroup = 4
    onlineController={}
    engine = create_engine(db)
    meta = MetaData(engine, reflect=True)
    table = meta.tables['callsigns']
    table2 = meta.tables['online']
    table3 = meta.tables['users']
    ts_ids = meta.tables['ts_user']
    ts_MessageLog = meta.tables['ts_message_log']
    def updatePos(ts3conn):
        conn = engine.connect()
        positionsAll = conn.execute(select([table])).fetchall()
        j= table2.join(table3, table3.c.cid == table2.c.cid).join(table, table2.c.callsign== table.c.callsign)
        onlineAll = conn.execute(select([table3.c.OI,table.c.identifier]).select_from(j)).fetchall()
        j2= table2.join(table3, table3.c.cid == table2.c.cid).join(table, table2.c.callsign== table.c.reliefCallsign1)
        onlineAll2 = conn.execute(select([table3.c.OI,table.c.identifier]).select_from(j2)).fetchall()
        #print(onlineAll)
        for onlinePos in onlineAll:
            if onlinePos[1] not in onlineController:
                onlineController[onlinePos[1]] = []
            onlineController[onlinePos[1]].append('('+onlinePos[0]+')')
        for onlinePos in onlineAll2:
            if onlinePos[1] not in onlineController:
                onlineController[onlinePos[1]] = []
            onlineController[onlinePos[1]].append('('+onlinePos[0]+')')
        #print(onlineController)
        for position in positionsAll:
            positions.append(position['identifier'])
        #print(positions)
        #resp = ts3conn.servergroupcopy(ssgid=sourceGroup, tsgid=0, name='6C', type_=1)
        #print(resp.parsed[0]['sgid'])
        resp = ts3conn.servergrouplist()
        for group in resp:
            groups[group['name']]=int(group['sgid'])
        for group in groups:
            if group in positions and group not in onlineController:
                try:
                    ts3conn.servergroupdel(sgid=groups[group], force=1 )
                except:
                    pass
        for position in onlineController:
            time.sleep(1)
            #print(position)
            if position not in groups:
                resp = ts3conn.servergroupcopy(ssgid=sourceGroup, tsgid=0, name=position, type_=1)
                groups[position]=int(resp.parsed[0]['sgid'])
            for controller in onlineController[position]:
                try:
                    resp = ts3conn.clientfind(pattern=controller) 
                    resp = ts3conn.clientgetuidfromclid(clid=resp.parsed[0]['clid'])
                    resp = ts3conn.clientgetdbidfromuid(cluid= resp.parsed[0]['cluid'])
                    print(resp.parsed[0]['cldbid']) 
                    print ('add ' + controller +' to ' +position)
                    ts3conn.servergroupaddclient(sgid=groups[position], cldbid= resp.parsed[0]['cldbid'])
                except:
                    print ('FAILED add ' + controller +' to ' +position)
            resp = ts3conn.servergroupclientlist(sgid=groups[position])
            #print('CHECK REMOVE')
            for user in resp.parsed:
                #print(user)
                resp = ts3conn.clientgetnamefromdbid(cldbid=user['cldbid'])
                #print(resp.parsed[0]['name'][-4:])
                #print(onlineController[position])
                if resp.parsed[0]['name'][-4:] not in onlineController[position]:
                    ts3conn.servergroupdelclient(sgid=groups[position], cldbid= resp.parsed[0]['cldbid'])
        print(groups)
    def updateUsers():
        def sendMessageReg(client_unique_identifier,clid):
            #give UID send mmessage to user (DONT RESEND FOR X TIME)
            #This works. Only issue is you Laraval cant accept a slash in Unicode and treats it as a normal slash in the url. Instead we need to pass with a get param or within a post. I am down for either, Post may be easier as it allows it to forward through.
            ts3conn.sendtextmessage(targetmode=1, target=clid, msg='Your teamspeak account is not registered with NYARTCC. In order to update Your positions, ratings and ARTCC status please click here https://nyartcc.org/ts/reg/set?uidStringID={}'.format(urllib.parse.quote_plus(client_unique_identifier)))
            #print('send message')
            return
        def sendBadUsername():
            #give UID send mmessage to user (DONT RESEND FOR X TIME)
            pass   
        #get all users in TS and retrun as resp
        #getAllActiveUsers select from TS users link to users via CID. Allows for multiple Idents 
        def checkLastMessage(uid,messageType):
            dbuserInfo = conn.execute(select([ts_MessageLog]).where(ts_MessageLog.c.uid==uid)).fetchone()
            if dbuserInfo:
                return dbuserInfo['time']
            else:
                conn.execute(insert(ts_MessageLog),[{"uid": uid, "type": messageType, "time" : 0},])
                return 0
        def updateLastMessage(uid,messageType,time):
            conn.execute(update(ts_MessageLog).where(ts_MessageLog.c.uid == uid).values(time=time))
            return
        resp = ts3conn.clientlist()
        conn = engine.connect()
        rawTsIds = conn.execute(select([ts_ids])).fetchall()
        allTeamspeakIds = []
        for ts_id in rawTsIds:
            allTeamspeakIds.append(ts_id['uid'])

        for user in resp.parsed:
            userInfo = ts3conn.clientinfo(clid=user['clid'])
            #print( userInfo.parsed[0]['client_type'])
            if userInfo.parsed[0]['client_type'] != '0':
                pass
            #checkDB for user in by user prim key of UID which will link CID to user

            elif userInfo.parsed[0]['client_unique_identifier'] in allTeamspeakIds:
                #check if user in rating group
                #check if user is guest of nyartcc and assign
                pass
            else:
                if checkLastMessage(userInfo.parsed[0]['client_unique_identifier'],'reg') < int(userInfo.parsed[0]['client_lastconnected']):
                    updateLastMessage(userInfo.parsed[0]['client_unique_identifier'],'reg', int(userInfo.parsed[0]['client_lastconnected']))
                    sendMessageReg(userInfo.parsed[0]['client_unique_identifier'],user['clid'])
                pass
                #send link to user to register self

  
        

    with ts3.query.TS3Connection(tsHostname, '10011') as ts3conn:
        ts3conn.login(client_login_name=tsUsername, client_login_password=tsPass)
        ts3conn.use(sid=1)
        updatePos(ts3conn)
        updateUsers()

lambda_handler('event', 'context')
