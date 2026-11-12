import boto3
import json
import logging
import os
from botocore.exceptions import WaiterError, ClientError

ec2 = boto3.client('ec2')
VALID_ACTIONS = ['start', 'stop', 'status']

LOG_LEVEL = logging.INFO
if os.environ.get('DEBUG', False):
    LOG_LEVEL = logging.DEBUG
LIMIT_TO_INSTANCE_IDS = [i.strip() for i in raw.split(",") if i.strip()] if (raw := os.getenv("INSTANCEID")) else None

# Initialize the root logger and set its level
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)


def lambda_handler(event, context):
    # logger.info(f"Received Event: {event}")
    query_params = event.get('queryStringParameters') or {}

    # Retrieve action from query string parameters
    action = query_params.get('action', None)
    # Retrieve instance_id from query string parameters
    instance_id = query_params.get('instance_id', None)

    if not action and not instance_id:
        logger.debug('No instance ID or action present - abort early')
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing required query parameter(s)'})
        }

    if LIMIT_TO_INSTANCE_IDS and instance_id not in LIMIT_TO_INSTANCE_IDS:
        logger.debug('Given instance ID not in allowed list - abort early')
        return {
            'statusCode': 403,
            'body': json.dumps({'error': 'Not allowed'})
        }

    if action.lower() not in VALID_ACTIONS:
        logger.debug('Invalid action provided - abort early')
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid action'})
        }

    action = action.lower()

    try:
        # Check the status of the instance
        logger.info(f"Checking status of instance {instance_id}")
        instance_status = ec2.describe_instances(InstanceIds=[instance_id])
        logger.debug(f"Instance info: {instance_status}")

        for reservation in instance_status['Reservations']:
            for instance in reservation['Instances']:
                # ( pending | running | shutting-down | terminated | stopping | stopped)
                instance_state = instance.get('State').get('Name')

        status_code = 200
        match action:
            case 'status':
                message = f"Instance {instance_id} current state: {instance_state}"

            case 'stop':
                if 'running' in instance_state:
                    # Stop the EC2 instance
                    ec2.stop_instances(InstanceIds=[instance_id])
                    waiter = ec2.get_waiter('instance_stopped')
                    waiter.wait(InstanceIds=[instance_id],
                                WaiterConfig={
                                    'Delay': 15,        # Poll every 15 seconds
                                    'MaxAttempts': 4    # 15s * 4 = 60 seconds
                                })
                    message = f'Instance {instance_id} successfully stopped'
                elif 'stopped' in instance_state:
                    message = f'Instance {instance_id} already stopped'
                else:
                    status_code = 500
                    message = f'Asked to stop instance {instance_id}, but not in running state'

            case 'start':
                match instance_state:
                    case 'stopped':
                        logger.info(f"Instance in stopped state - starting and waiting...")
                        # Start the EC2 instance
                        ec2.start_instances(InstanceIds=[instance_id])
                        # Wait for the instance to transition to the 'running' state
                        waiter = ec2.get_waiter('instance_running')
                        waiter.wait(InstanceIds=[instance_id],
                                    WaiterConfig={
                                        'Delay': 15,        # Poll every 15 seconds
                                        'MaxAttempts': 4    # 15s * 4 = 60 seconds
                                    })
                        message = "Instance started successfully"

                    case 'pending':
                        logger.info(f"Instance in pending state - wait...")
                        # Wait for the instance to transition to the 'running' state
                        waiter = ec2.get_waiter('instance_running')
                        waiter.wait(InstanceIds=[instance_id],
                                    WaiterConfig={
                                        'Delay': 15,        # Poll every 15 seconds
                                        'MaxAttempts': 4    # 15s * 4 = 60 seconds
                                    })
                        message = "Instance started successfully"

                    case 'running':
                        logger.info(f"Instance in running state - continue")
                        # Nothing to do
                        message = "Instance already running"
                        pass

                    case 'stopping' | 'shutting-down':
                        logger.info(f"Instance in stopping or shutting-down state - abort")
                        status_code = 500
                        message = f'Instance in {instance_state} state'

                    case 'terminated':
                        logger.info(f"Instance in terminated state - abort")
                        status_code = 500
                        message = f'Instance has been terminated'
        
        # Retrieve the public IP address
        response = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = None
        
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                public_ip = instance.get('PublicIpAddress')
                logger.info(f"Found Public IP: {public_ip}")

        body = {
            'message': message,
            'instanceId': instance_id
        }
        if public_ip:
            body['publicIp'] = public_ip

        return {
            'statusCode': status_code,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(body)
        }

    except ClientError as e:
        error_info = e.response.get("Error", {})
        error_code = error_info.get("Code", "Unknown")

        if error_code == "InvalidInstanceID.NotFound":
            status_code = 404
            message = f"Instance {instance_id} does not exist."
        elif error_code == "InvalidInstanceID.Malformed":
            status_code = 400
            message = f"The instance ID {instance_id} is not properly formatted."
        else:
            status_code = 500
            message = f"AWS ClientError ({error_code}): {error_info.get('Message', str(e))}"

    except WaiterError as e:
        status_code = 500
        last_error = (e.last_response or {}).get("Error", {})
        error_code = last_error.get("Code", "WaiterTimeout")
        message = f"Waiter failed ({error_code}): {e}"

    except Exception as e:
        status_code = 500
        message = str(e)

    return {
        'statusCode': status_code,
        'body': json.dumps({'error': message})
    }
