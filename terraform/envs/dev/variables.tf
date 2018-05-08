variable "deployment_stage" {
  type = "string"
  default = "dev"
}
variable "bucket_name_prefix" {
  type = "string"
}
variable "vpc_id" {
  type = "string"
}

variable "vpc_default_security_group_id" {
  type = "string"
}
variable "validation_cluster_ec2_key_pair" {
  type = "string"
}

variable "validation_cluster_ami_id" {
  type = "string"
}
variable "csum_cluster_ec2_key_pair" {
  type = "string"
}

variable "vpc_rds_security_group_id" {
  type = "string"
}
variable "db_username" {
  type = "string"
}
variable "db_password" {
  type = "string"
}
