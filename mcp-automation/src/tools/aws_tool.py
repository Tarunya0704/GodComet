"""AWS automation tool"""
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class AWSTool:
    """AWS operations"""
    
    def __init__(self, access_key: str, secret_key: str, region: str = 'us-east-1'):
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        self.region = region
        logger.info(f"AWS client initialized (region: {region})")
    
    async def create_bucket(self, bucket_name: str) -> Dict[str, Any]:
        """Create S3 bucket"""
        try:
            if self.region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )
            
            return {
                "success": True,
                "message": f"Bucket '{bucket_name}' created",
                "bucket": bucket_name
            }
        except ClientError as e:
            return {"success": False, "error": str(e)}
    
    async def list_buckets(self) -> Dict[str, Any]:
        """List S3 buckets"""
        try:
            response = self.s3.list_buckets()
            buckets = [b['Name'] for b in response['Buckets']]
            
            return {
                "success": True,
                "message": f"Found {len(buckets)} buckets",
                "buckets": buckets
            }
        except Exception as e:
            return {"success": False, "error": str(e)}