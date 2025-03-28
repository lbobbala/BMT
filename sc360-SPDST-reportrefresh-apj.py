#DEV SPDST APJ LAMBDA: sc360-SPDST-reportrefresh-apj
import json
import os
from multiprocessing import Process, JoinableQueue
import sys
import traceback
from datetime import datetime
from datetime import date
from datetime import timedelta
import boto3
import datetime
import time
import ast
import psycopg2
import re
import calendar
from time import gmtime, strftime

def send_sns_message(env,missing_file,process_name,region):
    loggroupname = os.environ['AWS_LAMBDA_LOG_GROUP_NAME']
    Logstream = os.environ['AWS_LAMBDA_LOG_STREAM_NAME']
    
    sns_message = {
                   "Env": env,
                   "Missing Priority File": missing_file,
                   "Process Name failed, If any": process_name,
                   "Region": region,
                   "Lambda_Name": os.environ['AWS_LAMBDA_FUNCTION_NAME'],
                   "Log Group": loggroupname,
                   "CloudWatch_Logstream": Logstream
            }
            
    print("inside sns function")
    sns_subject = '*** '+region + ' SPDST Priority File Missing ***'
    sns = boto3.client('sns')
    snsarn = os.environ['sns_arn']
    snsMessage = json.dumps(sns_message)
    sns.publish(
        TargetArn=snsarn,
        Message=snsMessage,
        Subject=sns_subject
    )
    print("msg sent")
    
def send_sns_message_failed(env,missing_file,process_name,region):
    loggroupname = os.environ['AWS_LAMBDA_LOG_GROUP_NAME']
    Logstream = os.environ['AWS_LAMBDA_LOG_STREAM_NAME']
    
    sns_message = {
                   "Env": env,
                   "Priority File Failed": missing_file,
                   "Process Name failed, If any": process_name,
                   "Region": region,
                   "Lambda_Name": os.environ['AWS_LAMBDA_FUNCTION_NAME'],
                   "Log Group": loggroupname,
                   "CloudWatch_Logstream": Logstream
            }
    print("inside sns function")
    sns_subject = '*** '+region + ' Priority File Failure ***'
    sns = boto3.client('sns')
    snsarn = os.environ['sns_arn']
    snsMessage = json.dumps(sns_message)
    sns.publish(
        TargetArn=snsarn,
        Message=snsMessage,
        Subject=sns_subject
    )
    print("msg sent")


def check_priority_apj_sfdc_check(rds_cursor,reportregion,BatchRunDate,d,env):
    #####################
    # check if APJ OPEN SFDC file is loaded to published.
    try:
        execution_status ='NULL'
        error_message='NULL'
        print('Checking APJ OPEN SFDC file if it is loaded')
        if (int(d.hour) == 3 and int(d.minute) > 5 and int(d.minute) < 30) :   # 8:40 ist - 3:10 UTC 
            sfdc_check_query = """Select count(*) from audit.sc360_audit_log where filename = 'APJ_OPEN_SFDC' 
                                    and processname = 'RedshiftPublishedLoad' and batchrundate = '{0}' and executionstatus = 'Succeeded';""".format(BatchRunDate)
            rds_cursor.execute(sfdc_check_query,)
            get_result = rds_cursor.fetchall()
            
            sfdc_sns_flag = 0
            if get_result[0][0] >0:
                sfdc_sns_flag = 0
                
            else:
            
                s3client = boto3.client('s3')
                landingBucketName = 'sc360-' + env + '-' + reportregion.lower() + '-bucket'
                landingFolder = 'LandingZone/dt=' + str(BatchRunDate + timedelta(days=1)) + '/'
                all_objects = s3client.list_objects_v2(Bucket=landingBucketName, Prefix=landingFolder, MaxKeys=350)
                LandingdataFileNameList = []
                try:
                    for obj in all_objects['Contents']:
                        filePath = obj['Key']
                        completeFileName = filePath.split('/')[-1]
                        if len(completeFileName) > 0 and not (completeFileName.startswith('SC360metadata_')):
                            LandingdataFileNameList.append(completeFileName)
                        else:
                            continue
                except Exception as e:
                    pass
    
                archiveFolder = 'ArchiveZone/dt=' + str(BatchRunDate + timedelta(days=1)) + '/'
                all_objects = s3client.list_objects_v2(Bucket=landingBucketName, Prefix=archiveFolder, MaxKeys=350)
                ArchivedataFileNameList = []
                try:
                    for obj in all_objects['Contents']:
                        filePath = obj['Key']
                        completeFileName = filePath.split('/')[-1]
                        if len(completeFileName) > 0 and not (completeFileName.startswith('SC360metadata_')):
                            ArchivedataFileNameList.append(completeFileName)
                        else:
                            continue
                except Exception as e:
                    pass
                
                filereceivedflag = 0
                for filename in LandingdataFileNameList:
                    if 'APJ_OPEN_SFDC' in filename:
                        print('This file is present in landingzone')
                        filereceivedflag = 1
                        break
                    else:
                        continue
                    
                for filename in ArchivedataFileNameList:
                    if 'APJ_OPEN_SFDC' in filename:
                        print('This file is present in ArchiveZone')
                        filereceivedflag = 1
                        break
                    else:
                        continue
                
                
                rds_cursor.execute("""Select distinct processname from audit.sc360_audit_log where filename = 'APJ_OPEN_SFDC' 
                                    and batchrundate = '{0}' 
                                    and executionstatus = 'Failed'; """.format(BatchRunDate))
                is_failed_res = rds_cursor.fetchall()
                if len(is_failed_res) >0:
                    # file loading failed at certain process
                    filesfailed = ['APJ_OPEN_SFDC Failed']
                    process = is_failed_res
                    print('Sending sns for apj open sfdc failed file')
                    send_sns_message_failed(env,filesfailed,process,reportregion)
                else:
                    # we have not received the file
                    if filereceivedflag == 0:
                        sfdc_filenotreceived = ['APJ_OPEN_SFDC']
                        print('Sending sns for apj open sfdc missing file')
                        send_sns_message(env,sfdc_filenotreceived,'NA',reportregion)
                    else:
                        pass
        else:
            print('Outside APJ Open SFDC sns time range')
    except Exception as e:
        print('Error in handling open sfdc sns logic ', str(e))
    #####################


def check_priority_file_load(filename,batchrunDate,region,filesfailed,filesnotreceived,rds_cursor,env):
    print('Checking current day',batchrunDate,' for missing file', filename)
    BatchRunDate = batchrunDate
    reportregion = region
    pfile = filename
    rds_cursor.execute("""select distinct filename  from audit.sc360_audit_log sal
    where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftCuratedLoad' and
    executionstatus = 'Succeeded' and filename = '{2}'""".format(BatchRunDate, reportregion,pfile))
    filesloaded_curated = rds_cursor.fetchall()

    loadedcuratedfiles = []
    for loadedfile in filesloaded_curated:
        loadedcuratedfiles.append(loadedfile[0])

    # get the execution status for the procedure of each files.
    procs_list = []
    for loadedfile in loadedcuratedfiles:
        rds_cursor.execute("""select distinct stored_procedure_name  from audit.sps_batch_master_table_updated sbmtu 
                            where regionname  = '{0}' and source_filename like '%{1}%';""".format(reportregion, loadedfile))

        file_stored_procs = rds_cursor.fetchall()
        if len(file_stored_procs) != 0:
            procs_list.append([loadedfile,file_stored_procs[0][0]])
    
    # print('File stored procedure names = ', procs_list)
    final_files = []
    for procs in procs_list:
        x = re.findall(" \(\);$", procs[1])
        if x:
          pass
        else:
          each_Sps1 = procs[1].replace("('","(''")
          each_Sps2 = each_Sps1.replace("')","'')")
          procs[1] = each_Sps2   # to convert to PUBLISHED.SP_CURTOPUB_R_REVENUE_EGI (''EMEA'')
              
        rds_cursor.execute("""select count(*)  from audit.sc360_audit_log sal
            where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftPublishedLoad' and
        executionstatus = 'Succeeded' and scriptpath = '{2}';""".format(BatchRunDate, reportregion, procs[1]))
        final_load_files_list = rds_cursor.fetchall()
        if final_load_files_list[0][0]> 0:
            final_files.append(procs[0])
    
    # print('Final Files List Loaded to published',final_files)
    loadedPublishedFiles = final_files
    if len(loadedPublishedFiles) == 1 and loadedPublishedFiles[0] == pfile:
        print('Priority file',pfile,' recieved and loaded in current date ',BatchRunDate )
        execution_status ='Delay'
        error_message='NULL'
        return 1
    else:
        
        rds_cursor.execute("""select count(*) from audit.sc360_audit_log where filename = '{0}' and processname = 'DataValidation' 
            and errormessage like '%list index out of rangeException caught while converting the SCITS file to relational in scits_data_conversion_to_relational function.%'
            and batchrundate = '{1}' and sourcename like '%.dat';""".format(pfile,BatchRunDate))
        
        sourcefilecount = rds_cursor.fetchall()
        if sourcefilecount[0][0] >0:
            print('This scits is empty from source and has no data records')
            execution_status ='Delay'
            error_message='NULL'
            return 1
        else:
            pass
            
        s3client = boto3.client('s3')
        landingBucketName = 'sc360-' + env + '-' + reportregion.lower() + '-bucket'
        landingFolder = 'LandingZone/dt=' + str(BatchRunDate) + '/'
        all_objects = s3client.list_objects_v2(Bucket=landingBucketName, Prefix=landingFolder, MaxKeys=350)
        LandingdataFileNameList = []
        try:
            for obj in all_objects['Contents']:
                filePath = obj['Key']
                completeFileName = filePath.split('/')[-1]
                if len(completeFileName) > 0 and not (completeFileName.startswith('SC360metadata_')):
                    LandingdataFileNameList.append(completeFileName)
                else:
                    continue
        except Exception as e:
            pass

        archiveFolder = 'ArchiveZone/dt=' + str(BatchRunDate) + '/'
        all_objects = s3client.list_objects_v2(Bucket=landingBucketName, Prefix=archiveFolder, MaxKeys=350)
        ArchivedataFileNameList = []
        try:
            for obj in all_objects['Contents']:
                filePath = obj['Key']
                completeFileName = filePath.split('/')[-1]
                if len(completeFileName) > 0 and not (completeFileName.startswith('SC360metadata_')):
                    ArchivedataFileNameList.append(completeFileName)
                else:
                    continue
        except Exception as e:
            pass
        
        filereceivedflag = 0
        for filename in LandingdataFileNameList:
            if pfile in filename:
                print('This file is present in landingzone current date folder but not yet processed',pfile)
                filereceivedflag = 1
                break
            else:
                continue
            
        for filename in ArchivedataFileNameList:
            if pfile in filename:
                print('This file is present in ArchiveZone current date folder',pfile)
                filereceivedflag = 1
                break
            else:
                continue
            
        rds_cursor.execute("""select distinct processname  from audit.sc360_audit_log sal 
        where batchrundate = '{0}' and executionstatus  like '%Failed%' and filename like '%{1}%'  ;""".format(BatchRunDate, pfile))
        failedprocesses = rds_cursor.fetchall()
        
        if len(failedprocesses) == 0:
            if filereceivedflag == 0:
                print("priority File not received yet in current date", pfile)
                filesnotreceived.append(pfile)
            else:
                pass
        else:
            print("priority failed in current date folder", failedprocesses)
            filesfailed.append({pfile:failedprocesses})
            execution_status ='Delay'
            error_message='priority failed in current date folder : '+str(pfile)
            print('return 0')
        return 0

def lambda_handler(event, context):

    d = datetime.datetime.utcnow()
    d_now = datetime.datetime.now()
    
    dependent_job1 = os.environ['dependent_job1']
    dependent_job2 = os.environ['dependent_job2']
    dependent_job3 = os.environ['dependent_job3']
    glueclient = boto3.client('glue')
    reportregion = os.environ['reportregion']
    
    env = os.environ['env']
    
    priorityFlag = 'YES'
    todaysDate = date.today()
    BatchRunDate = todaysDate - timedelta(days=1)
    dayofweek = calendar.day_name[BatchRunDate.weekday()]
    
    #Redshift Variables
    redshift_secret_name = os.environ['redshift_secret_name']
    rds_secret_name = os.environ['rds_secret_name']
    region_name = "us-east-1"
    secrets_client = boto3.client('secretsmanager', region_name=region_name)

    redshift_conn_string = ""
    # Get the secret details
    response = secrets_client.get_secret_value(
        SecretId=redshift_secret_name
    )

    # Get the secret values
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        print("redshift if")
        redshift_database = ast.literal_eval(response['SecretString'])['redshift_database']
        redshift_port = ast.literal_eval(response['SecretString'])['redshift_port']
        redshift_username = ast.literal_eval(response['SecretString'])['redshift_username']
        redshift_password = ast.literal_eval(response['SecretString'])['redshift_password']
        redshift_host = ast.literal_eval(response['SecretString'])['redshift_host']

        redshift_conn_string = "dbname='" + redshift_database + "' port='" + str(
            redshift_port) + "' user='" + redshift_username + "' password='" + redshift_password + "' host='" + redshift_host + "'"
        
    else:
        print("Not Able to extract Credentials for Redshift Connections")
        sys.exit("Not Able to extract Credentials for Redshift Connections")

    redshift_connection = psycopg2.connect(redshift_conn_string)
    redshift_cursor = redshift_connection.cursor()

    rds_conn_string = ""
    # Get the RDS secret details
    response = secrets_client.get_secret_value(
        SecretId=rds_secret_name
    )

    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        print("rds if")
        rds_database = ast.literal_eval(response['SecretString'])['engine']
        rds_port = ast.literal_eval(response['SecretString'])['port']
        rds_username = ast.literal_eval(response['SecretString'])['username']
        rds_password = ast.literal_eval(response['SecretString'])['password']
        rds_host = ast.literal_eval(response['SecretString'])['host']
        # rds_region = ast.literal_eval(response['SecretString'])['rds_region']

        rds_conn_string = "dbname='" + rds_database + "' port='" + str(
            rds_port) + "' user='" + rds_username + "' password='" + rds_password + "' host='" + rds_host + "'"
        
    else:
        print("Not Able to extract Credentials for RDS Connections")
        sys.exit("Not Able to extract Credentials for RDS Connections")

    rds_connection = psycopg2.connect(rds_conn_string)
    rds_cursor = rds_connection.cursor()
    
    # check apj priority file.
    check_priority_apj_sfdc_check(rds_cursor,reportregion,BatchRunDate,d,env)
    #calculation of start & end timings 
    rds_connection = psycopg2.connect(rds_conn_string)
    rds_cursor = rds_connection.cursor()
    # To  update the table 
    print("update1")
    start_now = str(date.today()) # 05-07-2022
    rds_cursor.execute("""select Expected_Start_time from audit.Master_Data_For_Report_Refresh where regionname = '{0}' 
    and report_source like '%SPDST%';""".format(reportregion))
    expectedstart = rds_cursor.fetchall() 
    print(expectedstart) #[(datetime.time(11, 15),)]
    expectedstart1=expectedstart[0][0]
    print(expectedstart1) #11:15:00
    print(type(expectedstart1)) # <class 'datetime.time'>
    print(start_now) #2022-07-05
    print(type(start_now)) # <class 'str'>
    # To update expected_end_time using average run time 
    rds_cursor.execute("""select Average_runtime from audit.Master_Data_For_Report_Refresh where regionname = '{0}' 
    and report_source like '%SPDST%';""".format(reportregion))
    averagerun = rds_cursor.fetchall()
    print(averagerun) #[(55,)]
    averagerun1=averagerun[0][0]
    print(averagerun1) #55
    x=expectedstart1
    date_format_str= '%H:%M:%S'
    x=str(x)
    y = datetime.datetime.strptime(x, date_format_str)
    final_time =y + timedelta(minutes=averagerun1)
    print('final time',final_time) # final time 1900-01-01 12:10:00
    result = str(final_time)
    end_time=result[11::]
    print(end_time) # 12:10:00
    join_start=" ".join([start_now, str(expectedstart1)])
    f = "%Y-%m-%d %H:%M:%S"
    join_start = datetime.datetime.strptime(join_start, f)
    print('join_start',join_start)
    print(type(join_start))
    join_end=" ".join([start_now, end_time])
    f = "%Y-%m-%d %H:%M:%S"
    join_end = datetime.datetime.strptime(join_end, f)
    #print("updatingtable")
    
    # To check table entry
    rds_connection = psycopg2.connect(rds_conn_string)
    rds_cursor = rds_connection.cursor()
    rds_cursor.execute("""select count(*) from audit.sc360_reportrefreshtrigger_log where regionname = '{1}' and batchrundate = '{0}'
    and report_source = 'SPDST';""".format(BatchRunDate + timedelta(days=1),reportregion))
    E = rds_cursor.fetchall()
    print('E',E)
    if E[0][0]>0:
    
        rds_connection = psycopg2.connect(rds_conn_string)
        rds_cursor = rds_connection.cursor()
        rds_cursor.execute("""select count(*) from audit.sc360_reportrefreshtrigger_log 
        where regionname = '{1}' and batchrundate = '{0}' and report_source = 'SPDST' ;""".format(BatchRunDate + timedelta(days=1),reportregion))
        Refreshcount = rds_cursor.fetchall()
        #execution_status=[]
        rds_cursor.execute("""select execution_status from audit.sc360_reportrefreshtrigger_log where regionname = '{1}' and batchrundate = '{0}'
        and report_source = 'SPDST';""".format(BatchRunDate + timedelta(days=1),reportregion))
        execution_status = rds_cursor.fetchall()
        #execution_status.append(execution_status1)
        print('es',execution_status)
        #print('es1',execution_status1)
        print("Refreshcount",Refreshcount[0][0])
        if Refreshcount[0][0] != 0 and len(execution_status)>0 and execution_status[0][0] in('Finished','Submitted'):
            e = "Report Refresh Triggered for the day already : " + str(BatchRunDate +timedelta(days=1))
            sys.exit(e)
        
        
        dependent_glue_response1 = glueclient.get_job_runs(JobName=dependent_job1)
        status_dependent_job1 = dependent_glue_response1['JobRuns'][0]['JobRunState']
        print("status_dependent_job1",status_dependent_job1)
        
        dependent_glue_response2 = glueclient.get_job_runs(JobName=dependent_job2)
        status_dependent_job2 = dependent_glue_response2['JobRuns'][0]['JobRunState']
        print("status_dependent_job2",status_dependent_job2)

        dependent_glue_response3 = glueclient.get_job_runs(JobName=dependent_job3)
        status_dependent_job3 = dependent_glue_response3['JobRuns'][0]['JobRunState']
        print("status_dependent_job2",status_dependent_job3)
        
        # dependent_glue_response3 = glueclient.get_job_runs(JobName=current_job_name)
        # status_current_job = dependent_glue_response3['JobRuns'][0]['JobRunState']
        # print("status_current_job",status_current_job)
        other_region_flag = 0
        if status_dependent_job3 in ['STARTING','RUNNING','STOPPING'] or status_dependent_job2 in ['STARTING','RUNNING','STOPPING'] or status_dependent_job1 in  ['STARTING','RUNNING','STOPPING']:
             other_region_flag = 1
             print("Other Region Report Refresh is already running Other region Flag:- ",other_region_flag )
             if d > join_start:  
                 rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                 set  execution_status = 'Delay', error_message = 'Other Region Report Refresh is already running'
                 where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion))
                 rds_connection.commit()
        print('other_region_flag',other_region_flag)
        # if status_current_job in ['STARTING','RUNNING','STOPPING']:
        #      sys.exit("Region Report Refresh is already running")
            
        
        ##################################################################################################################
        ##################################################################################################################


        print("No other Glue Jobs are running")
        
        rds_cursor.execute("""select filename from audit.fileproperty_check_new fcn where 
            priorityflag = 'YES' and region = '{0}' and data_source not like 'BMT%';""".format(reportregion))
        priorityfiles = rds_cursor.fetchall()
        print("priorityfiles",priorityfiles)
        
        process_name = "NA"
        
        rds_cursor.execute("""select distinct filename  from audit.sc360_audit_log sal
        where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftCuratedLoad' and
        executionstatus = 'Succeeded';""".format(BatchRunDate, reportregion))
        filesloaded_curated = rds_cursor.fetchall()
        print("filesloaded_curated",filesloaded_curated)

        loadedcuratedfiles = []
        for loadedfile in filesloaded_curated:
            loadedcuratedfiles.append(loadedfile[0])
        print("Loaded files in curated", loadedcuratedfiles)
        
        # get the execution status for the procedure of each files.
        procs_list = []
        for loadedfile in loadedcuratedfiles:
            rds_cursor.execute("""select distinct stored_procedure_name  from audit.sps_batch_master_table_updated sbmtu 
                                where regionname  = '{0}' and source_filename like '%{1}%';""".format(reportregion, loadedfile))

            file_stored_procs = rds_cursor.fetchall()
            if len(file_stored_procs) != 0:
                procs_list.append([loadedfile,file_stored_procs[0][0]])
        
        
        print('File stored procedure names = ', procs_list)
        final_files = []
        for procs in procs_list:
            x = re.findall(" \(\);$", procs[1])
            if x:
              pass
            else:
              each_Sps1 = procs[1].replace("('","(''")
              each_Sps2 = each_Sps1.replace("')","'')")
              procs[1] = each_Sps2   # to convert to PUBLISHED.SP_CURTOPUB_R_REVENUE_EGI (''EMEA'')
                  
            rds_cursor.execute("""select count(*)  from audit.sc360_audit_log sal
                where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftPublishedLoad' and
            executionstatus = 'Succeeded' and scriptpath = '{2}';""".format(BatchRunDate, reportregion, procs[1],procs[0]))
            final_load_files_list = rds_cursor.fetchall()
            if final_load_files_list[0][0]> 0:
                final_files.append(procs[0])
        print('Final Files List Loaded to published',final_files)
        loadedPublishedFiles = final_files
        

        filesnotreceived = []
        filesfailed = []
        em=''
        pfcount = 0
        failedprocess = []
        pfilesfailed=[]
        for pfile in priorityfiles:
            if pfile[0] in loadedPublishedFiles: 
                execution_status ='NULL'
                error_message='NULL'
                print("Priority File loaded till Published", pfile[0] )
                if pfile[0][-3:] == 'PND':
                    # print('This is a scits file. Checking reference date of the file.')
                    rds_cursor.execute("""Select distinct destinationname from audit.sc360_audit_log where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftCuratedLoad' and
                    executionstatus = 'Succeeded' and filename like '%{2}%';""".format(BatchRunDate, reportregion,pfile[0]))
                    curated_table_name = rds_cursor.fetchall()
                    # print('Published table name of file',pfile[0],'is ', curated_table_name[0][0])
                    print(curated_table_name)
                    redshift_cursor.execute("""Select distinct reference_dt from {0} where source_nm like '%{1}%';""".format(curated_table_name[0][0],pfile[0]))
                    reference_dt = redshift_cursor.fetchall()
                    # print(reference_dt)
                    if reference_dt[0][0] == (BatchRunDate):
                        # print('Correct refrence_Dt for the file',pfile[0])
                        pfcount +=1
                    else:
                        print(pfile[0],' Loaded is todays file. Reference_Dt should be current_dt-1  ')
                        filesfailed.append({pfile[0]:'Reference_Dt not correct of the file. It should be current_dt - 1'})
                        
                else:        
                    pfcount += 1
        
            else:
                print("Priority File missing in previous date folder", BatchRunDate,pfile[0] )
                #execution_status ='DELAY' & error_message='Priority File missing in previous date folder with pfile[0]'
                s= str(filesnotreceived)
                em= s
                em1= em.replace("['","")
                em2= em1.replace("']","")
                em3=em2.replace("', '",",")
                em= em3
                execution_status ='Delay'
                error_message='Priority File missing in previous date folder  pfile : ' + str(em)
                rds_cursor.execute("""select count(*) from audit.sc360_audit_log where filename = '{0}' and processname = 'DataValidation' 
                and errormessage like '%list index out of rangeException caught while converting the SCITS file to relational in scits_data_conversion_to_relational function.%'
                and batchrundate = '{1}' and sourcename like '%.dat';""".format(pfile[0],BatchRunDate))
                
                sourcefilecount = rds_cursor.fetchall()
                if sourcefilecount[0][0] >0:
                    print('This scits is empty from source and has no data records')
                    pfcount += 1
                    continue
                else:
                    if check_priority_file_load(pfile[0],BatchRunDate +  timedelta(days=1),reportregion,filesfailed,filesnotreceived,rds_cursor,env) ==1:
                        # pfcount +=1
                        if pfile[0][-3:] == 'PND':
                            # print('This is a scits file. Checking reference date of the file.')
                            rds_cursor.execute("""Select distinct destinationname from audit.sc360_audit_log where batchrundate = '{0}' and regionname  = '{1}' and processname  = 'RedshiftCuratedLoad' and
                            executionstatus = 'Succeeded' and filename like '%{2}%';""".format(BatchRunDate + timedelta(days=1) , reportregion,pfile[0]))
                            curated_table_name = rds_cursor.fetchall()
                            # print('Published table name of file',pfile[0],'is ', curated_table_name[0][0])
                            
                            redshift_cursor.execute("""Select distinct reference_dt from {0} where source_nm like '%{1}%';""".format(curated_table_name[0][0],pfile[0]))
                            reference_dt = redshift_cursor.fetchall()
                            # print(reference_dt)
                            if reference_dt[0][0] == (BatchRunDate):
                                # print('Correct refrence_Dt for the file',pfile[0])
                                pfcount +=1
                            else:
                                print(pfile[0],' Loaded is todays file. Reference_Dt should be current_dt-1  ')
                                filesfailed.append({pfile[0]:'Reference_Dt not correct of the file. It should be current_dt - 1'})
                        else:        
                            pfcount += 1                    
                        continue
                    else:
                        
                        rds_cursor.execute("""select distinct processname  from audit.sc360_audit_log sal 
                        where batchrundate = '{0}' and executionstatus  like '%Failed%' and filename = '{1}'  ;""".format(BatchRunDate, pfile[0]))
                        failedprocesses = rds_cursor.fetchall()
                
                if len(failedprocesses) != 0:
                    print('pfile',pfile[0])
                    print("priority failed at", failedprocesses)
                    filesfailed.append({pfile[0]:failedprocesses})
                    pfilesfailed.append(pfile[0])
                    #@@@ execution_status= 'DELAY' error_message= 'priority failed in current date folder ,pfile[0]'
                    #Failes [{'A33SCPND': ['datavalidation']}, {'C33SCPND': ['datavalidation']}, {'
                    s= str(pfilesfailed)
                    em= s
                    print('em',em)
                    em1= em.replace("['","")
                    print('em1',em1)
                    em2= em1.replace("']","")
                    print('em2',em2)
                    em3=em2.replace("', '",",")
                    print('em3',em3)
                    em= em3
                    print('em',em)
                    execution_status ='Delay'
                    error_message='priority failed during the process for the current date : '+str(em)
                    print('error_message',error_message)
                    if d > join_start:
                        rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                        set  execution_status = '{2}', error_message = '{3}'
                        where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion,execution_status,error_message))
                        rds_connection.commit()
                        rds_cursor.execute("""select error_message from audit.sc360_reportrefreshtrigger_log
                        where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion))
                        z= rds_cursor.fetchall() 
                        print('check',z) 
        print('error_message',error_message)
        
        print('File Not received', filesnotreceived)
        print('File Failes', filesfailed)
                    
        print("pfcount",pfcount)
        
        cutoff_strt_hour = os.environ['cutoff_strt_hour']
        cutoff_strt_min = os.environ['cutoff_strt_minute']
        cutoff_end_hour = os.environ['cutoff_end_hour']
        cutoff_end_min = os.environ['cutoff_end_minute']
        glue_job = os.environ['glue_job']
        
        
        print("d.hour",d.hour) #7
        print("cutoff_strt_hour",cutoff_strt_hour) #7
        print("d.minute",d.minute) #20
        print("cutoff_strt_min", cutoff_strt_min) #15
        print("cutoff_end_hour", cutoff_end_hour) #7
        
        if (int(d.hour) >= int(cutoff_strt_hour) and int(d.minute) >= int(cutoff_strt_min)) and int(d.hour) <= int(cutoff_end_hour):
            snstimeperiod = 'YES'
        else:
            snstimeperiod = 'NO'
        print("SNS period",snstimeperiod)
        print(pfcount)
        print(len(priorityfiles))
        
        rds_cursor.execute("""select count(*) from audit.sc360_reportrefreshtrigger_log 
                where regionname = '{0}' and batchrundate = '{1}' and report_source = 'BMT' and execution_Status = 'Finished' ;""".format(reportregion,BatchRunDate+timedelta(days=1)))
        BMTRefreshcount = rds_cursor.fetchall()
        BMTFlag = 1
        if BMTRefreshcount[0][0] == 0:
            e = "BMT Report Refresh not Triggered/Finished for the day ..: " + str(BatchRunDate)
            if d > join_start:  
                rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                set execution_status = 'Delay',error_message = '{2}'
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1),reportregion,error_message))
                rds_connection.commit()
                print(error_message)
            BMTFlag = 0
            # sys.exit(e)
        
        print("BMT Refreshcount",BMTRefreshcount[0][0],"BMTFlag = ",BMTFlag)

        
        if pfcount == len(priorityfiles) and BMTFlag == 1 and other_region_flag == 0:
            if int(d.hour) >= 0 and int(d.hour) < 21:
                print("Priority Files Received, proceeding to process report refresh")
                
                region = reportregion
                sns_message = {
                               "Env": env,
                               "Message": 'The SPDST ' + region + ' Report refresh is started. Open glue job log : '+ str(glue_job),
                               "Region": region,
                               "Lambda_Name": os.environ['AWS_LAMBDA_FUNCTION_NAME'],
                               "Log Group": os.environ['AWS_LAMBDA_LOG_GROUP_NAME'],
                               "CloudWatch_Logstream": os.environ['AWS_LAMBDA_LOG_STREAM_NAME']
                        }
                        
                print("inside sns function")
                sns_subject = '*** '+region + ' SPDST report refresh is started.***'
                sns = boto3.client('sns')
                snsarn = os.environ['sns_arn']
                snsMessage = json.dumps(sns_message)
                sns.publish(
                    TargetArn=snsarn,
                    Message=snsMessage,
                    Subject=sns_subject
                )
                
                response = glueclient.start_job_run(
                  JobName=glue_job)
                 
                d = datetime.datetime.utcnow()
                #once my glue job starts it will update execution satus as submitted and glue job name , error msg
                rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                set Actual_Start_time ='{2}', execution_status = 'Submitted',error_message = 'NULL'
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1),reportregion,d))
                rds_connection.commit()
                print("glue job ")
            
                rds_update_query = """
                    Update audit.sc360_audit_log 
                    set Batchrundate = '{0}'
                    where regionname = 'APJ' and batchrundate = '{1}' and filename <> 'APJ_OPEN_SFDC';
                """.format(BatchRunDate,BatchRunDate + timedelta(days=1))
                rds_cursor.execute(rds_update_query)
            
            rds_connection.commit()
            print('Priority Files received for SPDST, triggering report refresh ')

        elif (pfcount != len(priorityfiles)) and snstimeperiod =='YES' :
            print("Cut off time Reached and priority files not received")
            message = "****Priority Files Not Received for the Region*****"
            s= str(filesnotreceived)
            em= s
            print('em',em)
            em1= em.replace("['","")
            print('em1',em1)
            em2= em1.replace("']","")
            print('em2',em2)
            em3=em2.replace("', '",",")
            print('em3',em3)
            em= em3
            print('em',em)
            error_message = 'Cut off time Reached and priority files not received : ' +str(em)
            print('error_message',error_message)
            print(type(error_message))
            if d > join_start:
                rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                set  execution_status = 'Delay', error_message = '{2}'
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion,error_message))
                rds_connection.commit()
                #print("errormsg1",error_message)
                rds_cursor.execute("""select error_message,execution_status  from audit.sc360_reportrefreshtrigger_log 
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion))
                z= rds_cursor.fetchall() 
                print('z',z)
            if len(filesnotreceived) > 0:
                region = reportregion
                process_name = 'Files Not Received'
                send_sns_message(env,filesnotreceived,'NA',reportregion)
                
            if len(filesfailed) > 0:
                region = reportregion
                process_name = 'NA'
                print("sending sns")
                print(filesfailed)
                send_sns_message_failed(env,filesfailed,process_name,reportregion)
        else:
            print("Priority Files Not rerceived yet, Monitoring the Load Status")
            s= str(filesnotreceived)
            em= s
            print('em',em)
            em1= em.replace("['","")
            print('em1',em1)
            em2= em1.replace("']","")
            print('em2',em2)
            em3=em2.replace("', '",",")
            print('em3',em3)
            em= em3
            print('em',em)
            error_message = 'Priority Files Not rerceived yet, Monitoring the Load Status : ', str(em), '/ BMTFlag = ' ,str(BMTFlag) ,'/other_region_flag',str(other_region_flag)
            print('error_message',error_message)
            error_msg = str(error_message)
            error_msg1= error_msg.replace("('","")
            error_msg2= error_msg1.replace("')","")
            error_msg3= error_msg2.replace("', '","")
            error_message = error_msg3
            print('error_message',error_message)
            print(type(error_message))
            if d > join_start: 
                rds_cursor.execute("""update audit.sc360_reportrefreshtrigger_log
                set  execution_status = 'Delay', error_message = '{2}'
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion,error_message))
                rds_connection.commit()
                #print("errormsg1",error_message)
                rds_cursor.execute("""select error_message,execution_status  from audit.sc360_reportrefreshtrigger_log 
                where batchrundate = '{0}' and regionname = '{1}' and report_source = 'SPDST';""" .format(BatchRunDate + timedelta(days=1), reportregion))
                z= rds_cursor.fetchall() 
                print('z',z)

        #######################################################################################################################
        #######################################################################################################################

        delay_cutoff_strt_hour = os.environ['delay_cutoff_strt_hour']
        delay_cutoff_strt_min = os.environ['delay_cutoff_strt_minute']
        delay_cutoff_end_hour = os.environ['delay_cutoff_end_hour']
        delay_cutoff_end_min = os.environ['delay_cutoff_end_minute']
        
        delay_snstimeperiod = 'NO'
        if (int(d.hour) >= int(delay_cutoff_strt_hour) and int(d.minute) >= int(delay_cutoff_strt_min)) and int(d.hour) <= int(delay_cutoff_end_hour) and int(d.minute) < int(delay_cutoff_end_min):
          delay_snstimeperiod = 'YES'
        else:
            delay_snstimeperiod = 'NO'
        print("Delay SNS period",delay_snstimeperiod)
        
        
        if delay_snstimeperiod == 'YES':
            rds_cursor.execute("""select distinct execution_status from audit.sc360_reportrefreshtrigger_log 
                where regionname = '{0}' and batchrundate = '{1}' and report_source = 'SPDST';""".format(reportregion,BatchRunDate+timedelta(days=1)))
            check_glue_job_status = rds_cursor.fetchall()
            print('Response:-',check_glue_job_status)
            
            if len(check_glue_job_status)==0 or check_glue_job_status[0][0] == 'Failed':
                sns_message = {
                          "Env": env,
                          "Report_Source":'SPDST',
                          "Region":reportregion,
                          "Message": 'There will Delay in Report_source for SPDST due to some issue.'
                }
                print("inside sns function")
                sns_subject = '*** Delay in '+reportregion + ' SPDST Report Refresh ***'
                sns = boto3.client('sns')
                snsarn = os.environ['delay_sns_arn']
                snsMessage = json.dumps(sns_message)
                sns.publish(
                    TargetArn=snsarn,
                    Message=snsMessage,
                    Subject=sns_subject
                )
                print("Delay msg sent to users.")
        else:
            pass
    else:
        print('Inserting table')      
        # To insert values into  table

        execution_status = 'Yet to start'
        glue_job = os.environ['glue_job']
        #actual_end_time = start_now
        error_message = 'SPDST report refresh yet to start'
        rds_insert_query = """
        INSERT INTO audit.sc360_reportrefreshtrigger_log(
        batchrundate, regionname, execution_status,gluejob, report_source,Expected_Start_time,Expected_End_time,error_message)
        VALUES(%s, %s, %s, %s, %s, %s, %s, %s);
        """
        records_insert = (
        BatchRunDate + timedelta(days=1), reportregion, execution_status,glue_job, 'SPDST',join_start,join_end,error_message)

        rds_cursor.execute(rds_insert_query, records_insert)
        rds_connection.commit()
        print("Inserted") 
        
        #######################################################################################################################
        #######################################################################################################################