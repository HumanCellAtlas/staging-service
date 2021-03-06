locals {
  bucket_name = "${var.bucket_name_prefix}${var.deployment_stage}"
  account_id = "${data.aws_caller_identity.current.account_id}"
  aws_region = "${data.aws_region.current.name}"
}

module "upload-vpc" {
  source = "../../modules/vpc"
  component_name = "upload"
  deployment_stage = "${var.deployment_stage}"
  vpc_cidr_block = "${var.vpc_cidr_block}"
}

module "upload-service-database" {
  source = "../../modules/database"
  deployment_stage = "${var.deployment_stage}"
  db_username = "${var.db_username}"
  db_password = "${var.db_password}"
  db_instance_count = "${var.db_instance_count}"
  pgbouncer_subnet_id = "${element(data.aws_subnet_ids.upload_vpc.ids, 0)}"
  lb_subnet_ids = "${data.aws_subnet_ids.upload_vpc.ids}"
  vpc_id = "${module.upload-vpc.vpc_id}"
  preferred_maintenance_window = "${var.preferred_maintenance_window}"
}
