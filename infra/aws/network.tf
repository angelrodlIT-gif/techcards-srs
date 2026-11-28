resource "aws_vpc" "pilot" {
  cidr_block           = "10.26.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_default_security_group" "pilot" {
  vpc_id = aws_vpc.pilot.id
}

resource "aws_subnet" "database" {
  for_each = {
    for index, zone in var.database_azs : tostring(index) => zone
  }

  vpc_id                  = aws_vpc.pilot.id
  availability_zone       = each.value
  cidr_block              = cidrsubnet(aws_vpc.pilot.cidr_block, 8, tonumber(each.key))
  map_public_ip_on_launch = false
}

resource "aws_route_table" "database" {
  vpc_id = aws_vpc.pilot.id
}

resource "aws_route_table_association" "database" {
  for_each = aws_subnet.database

  subnet_id      = each.value.id
  route_table_id = aws_route_table.database.id
}

resource "aws_security_group" "task" {
  for_each = toset(["api", "migration"])

  name        = "${var.name}-${each.key}"
  description = "Dedicated ${each.key} task identity"
  vpc_id      = aws_vpc.pilot.id
}

resource "aws_security_group" "database" {
  name        = "${var.name}-database"
  description = "Private PostgreSQL access"
  vpc_id      = aws_vpc.pilot.id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  for_each = aws_security_group.task

  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = each.value.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "postgres" {
  for_each = aws_security_group.task

  security_group_id            = each.value.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
