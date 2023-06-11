variable "lambda_function_name" {
  description = "The name of the Lambda function"
  default     = "get_zny_web_ip"
}

variable "vpc_id" {
  description = "The ID of the VPC"
}

variable "subnet_ids" {
  description = "The IDs of the subnets"
  type        = list(string)
}

variable "security_group_ids" {
  description = "The IDs of the security groups"
  type        = list(string)
}

# IAM role for the Lambda function
resource "aws_iam_role" "lambda_role" {
  name = "${var.lambda_function_name}_role"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF
}

# IAM policy allowing the necessary EC2 permissions
resource "aws_iam_policy" "lambda_ec2_policy" {
  name        = "${var.lambda_function_name}_ec2_policy"
  description = "Allows Lambda to describe EC2 instances"

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "ec2:DescribeInstances"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
EOF
}

# Attach the IAM policy to the role
resource "aws_iam_role_policy_attachment" "lambda_ec2_policy_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_ec2_policy.arn
}

# Create the Lambda function
resource "aws_lambda_function" "get_zny_web_ip" {
  filename      = "lambda_function_payload.zip"  # replace with the path to your zip file
  function_name = var.lambda_function_name
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"  # replace with your handler

  source_code_hash = filebase64sha256("lambda_function_payload.zip")  # replace with the path to your zip file

  runtime = "python3.9"

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  timeout = 300  # 5 minutes
}

# VPC Endpoint for EC2
resource "aws_vpc_endpoint" "ec2_endpoint" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.us-east-1.ec2"
  vpc_endpoint_type = "Interface"

  security_group_ids = var.security_group_ids
  subnet_ids         = var.subnet_ids

  private_dns_enabled = true
}

variable "s3_bucket" {
  description = "The name of the S3 bucket where the Lambda function code will be uploaded"
}

variable "lambda_code_directory" {
  description = "The directory where the Lambda function code is located"
  default     = "./lambda_function_code"
}


# Create a ZIP file from the Lambda function code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = var.lambda_code_directory
  output_path = "${var.lambda_code_directory}/lambda_function_payload.zip"
}

# Upload the ZIP file to S3
resource "aws_s3_bucket_object" "lambda_code" {
  bucket = var.s3_bucket
  key    = "${var.lambda_function_name}/lambda_function_payload.zip"
  source = data.archive_file.lambda_zip.output_path
  acl    = "private"
}


# Create the Lambda function
resource "aws_lambda_function" "get_zny_web_ip" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"  # replace with your handler

  s3_bucket = var.s3_bucket
  s3_key    = aws_s3_bucket_object.lambda_code.key

  runtime = "python3.10"

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  timeout = 300  # 5 minutes
}
