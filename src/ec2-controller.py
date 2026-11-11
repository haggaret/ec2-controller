import boto3
import json
import logging
import os

ec2 = boto3.client('ec2')

LOG_LEVEL = logging.INFO
if os.environ.get('DEBUG', False):
    LOG_LEVEL = logging.DEBUG

# Initialize the root logger and set its level
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)


def lambda_handler(event, context):
    # logger.info(f"Received Event: {event}")

    # Retrieve instance_id from query string parameters with fallback to ENV VAR
    query_params = event.get('queryStringParameters') or {}
    instance_id = query_params.get('instance_id') or os.environ.get('INSTANCEID', None)
    
    if not instance_id:
        logger.debug('No instance ID present - abort early')
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing query parameter: instance_id'})
        }
    
    try:
        # Check the status of the instance
        logger.info(f"Checking status of instance {instance_id}")
        instance_status = ec2.describe_instances(InstanceIds=[instance_id])
        logger.debug(f"Instance info: {instance_status}")

        for reservation in instance_status['Reservations']:
            for instance in reservation['Instances']:
                instance_state = instance.get('State').get('Name')

        message = "Unknown State"
        # ( pending | running | shutting-down | terminated | stopping | stopped)
        match instance_state:
            case 'stopped':
                logger.info(f"Instance in stopped state - starting and waiting...")
                # Start the EC2 instance
                ec2.start_instances(InstanceIds=[instance_id])
            
                # Wait for the instance to transition to the 'running' state
                waiter = ec2.get_waiter('instance_running')
                waiter.wait(InstanceIds=[instance_id])
                message = "Instance started successfully"

            case 'pending':
                logger.info(f"Instance in pending state - wait...")
                # Wait for the instance to transition to the 'running' state
                waiter = ec2.get_waiter('instance_running')
                waiter.wait(InstanceIds=[instance_id])
                message = "Instance started successfully"

            case 'running':
                logger.info(f"Instance in running state - continue")
                # Nothing to do
                message = "Instance already running"
                pass

            case 'stopping' | 'shutting-down':
                logger.info(f"Instance in stopping or shutting-down state - abort")
                return {
                    'statusCode': 500,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'message': 'Instance stopping/shutting down',
                        'instanceId': instance_id
                    })
                }

            case 'terminated':
                logger.info(f"Instance in terminated state - abort")
                return {
                    'statusCode': 500,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'message': 'Instance terminated',
                        'instanceId': instance_id
                    })
                }
        
        # Retrieve the public IP address
        response = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = None
        
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                public_ip = instance.get('PublicIpAddress')
                logger.info(f"Found Public IP: {public_ip}")

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'message': message,
                'instanceId': instance_id,
                'publicIp': public_ip
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
