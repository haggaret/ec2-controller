import boto3
import json
import os

ec2 = boto3.client('ec2')


def lambda_handler(event, context):
    # Retrieve instance_id from query string parameters
    query_params = event.get('queryStringParameters') or {}
    instance_id = query_params.get('instance_id') or os.environ.get('INSTANCEID', None)
    
    if not instance_id:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing missing query parameter: instance_id'})
        }
    
    try:
        # Check the status of the instance
        instance_status = ec2.describe_instances(InstanceIds=[instance_id])

        # "State": {
        #     "Code": 80,
        #     "Name": "stopped"
        # },
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_state = instance.get('State').get('Name')

        # ( pending | running | shutting-down | terminated | stopping | stopped)
        match instance_state:
            case 'stopped':
                # Start the EC2 instance
                ec2.start_instances(InstanceIds=[instance_id])
            
                # Wait for the instance to transition to the 'running' state
                waiter = ec2.get_waiter('instance_running')
                waiter.wait(InstanceIds=[instance_id])

            case 'pending':
                # Wait for the instance to transition to the 'running' state
                waiter = ec2.get_waiter('instance_running')
                waiter.wait(InstanceIds=[instance_id])

            case 'running':
                # Nothing to do
                pass

            case 'stopping' | 'shutting-down':
                return {
                    'statusCode': 500,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'message': 'Instance stopping/shutting down',
                        'instanceId': instance_id
                    })
                }

            case 'terminated':
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
                
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'message': 'Instance started successfully',
                'instanceId': instance_id,
                'publicIp': public_ip
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
