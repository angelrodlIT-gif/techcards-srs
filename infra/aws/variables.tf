variable "account_id" {
  description = "Approved AWS account for the pilot."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Use a 12-digit AWS account ID."
  }
}

variable "region" {
  description = "Approved AWS region."
  type        = string
}

variable "name" {
  description = "Unique pilot identifier used as the resource name prefix."
  type        = string

  validation {
    condition     = length(var.name) <= 30 && can(regex("^[a-z]([a-z0-9]|-[a-z0-9])*$", var.name))
    error_message = "Use a lowercase letter followed by up to 29 letters, digits, or nonconsecutive hyphens. End with a letter or digit."
  }
}

variable "database_azs" {
  description = "Two distinct Availability Zones in the approved region."
  type        = list(string)

  validation {
    condition     = length(var.database_azs) == 2 && length(distinct(var.database_azs)) == 2
    error_message = "Provide exactly two distinct Availability Zones."
  }
}

variable "final_snapshot_identifier" {
  description = "Unique name reserved for the encrypted final RDS snapshot."
  type        = string
}
