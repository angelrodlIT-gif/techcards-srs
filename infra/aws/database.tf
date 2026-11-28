resource "aws_db_subnet_group" "pilot" {
  name       = var.name
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]
}

resource "aws_db_parameter_group" "pilot" {
  name   = "${var.name}-postgres16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "pilot" {
  identifier                  = var.name
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  multi_az                    = false
  publicly_accessible         = false
  db_name                     = "techcards"
  username                    = "techcards_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.pilot.name
  parameter_group_name        = aws_db_parameter_group.pilot.name
  vpc_security_group_ids      = [aws_security_group.database.id]

  backup_retention_period   = 14
  copy_tags_to_snapshot     = true
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = var.final_snapshot_identifier
}
