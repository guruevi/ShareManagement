from flask_wtf import FlaskForm
from wtforms.fields.choices import SelectField, SelectMultipleField
from wtforms.fields.numeric import IntegerField
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange


class ShareForm(FlaskForm):
    customer = SelectField('Customer', choices=[], validators=[DataRequired()])
    folder_name = StringField('Folder Name', validators=[DataRequired()])
    quota = IntegerField('Quota (TB)', default=0,
                         validators=[NumberRange(min=0, message="Quota must be a positive number or 0 to unset")])
    server = SelectField('Server', choices=[], validators=[DataRequired()])
    protocol = SelectMultipleField('Protocol',
                                   choices=[('nfs', 'NFS'), ('smb', 'SMB'), ('s3', 'S3'), ('', 'Subfolder')])
    owner = StringField('Owner', validators=[DataRequired()])
    users = StringField('Users', validators=[DataRequired()])
    index = IntegerField('Permission Index',
                        validators=[NumberRange(min=-1, message="Permissions must have a positive index or -1 for POSIX")],
                        default=-1)
    permission = SelectField('Permission',
                             choices=[('rwx', 'Read and Write'), ('rx', 'Read Only'), ('r', 'Visible')])
    parent = SelectField('Parent Share', choices=[('', 'None')])  # New field

    submit = SubmitField('Submit')