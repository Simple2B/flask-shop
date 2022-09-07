# -*- coding: utf-8 -*-
"""User views."""
import os
from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    current_app,
)
from flask_login import login_required, current_user, login_user, logout_user
from flask_mail import Message
from pluggy import HookimplMarker
from flask_babel import lazy_gettext
import random
import string
from .forms import AddressForm, LoginForm, RegisterForm, ChangePasswordForm, ResetPasswd
from .models import UserAddress, User
from flaskshop.utils import flash_errors
from flaskshop.order.models import Order
from flaskshop.logger import log

impl = HookimplMarker("flaskshop")


# @app.route("/google/")
def google():
    GOOGLE_CLIENT_ID = current_app.config["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = current_app.config["GOOGLE_CLIENT_SECRET"]
    CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"
    current_app.oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=CONF_URL,
        client_kwargs={"scope": "openid email profile"},
    )

    # Redirect to google_auth function
    redirect_uri = url_for("google.google_auth", _external=True)
    return current_app.oauth.google.authorize_redirect(redirect_uri)


# @app.route("/google/auth/")
def google_auth():
    token = current_app.oauth.google.authorize_access_token()
    user = current_app.oauth.google.parse_id_token(token)
    log(log.INFO, f"user: {user}")
    return redirect("/")


def facebook():
    # Facebook Oauth Config
    FACEBOOK_CLIENT_ID = os.environ.get("FACEBOOK_CLIENT_ID")
    FACEBOOK_CLIENT_SECRET = os.environ.get("FACEBOOK_CLIENT_SECRET")
    current_app.oauth.register(
        name="facebook",
        client_id=FACEBOOK_CLIENT_ID,
        client_secret=FACEBOOK_CLIENT_SECRET,
        access_token_url="https://graph.facebook.com/oauth/access_token",
        access_token_params=None,
        authorize_url="https://www.facebook.com/dialog/oauth",
        authorize_params=None,
        api_base_url="https://graph.facebook.com/",
        client_kwargs={"scope": "email"},
    )
    redirect_uri = url_for("facebook.facebook_auth", _external=True)
    return current_app.oauth.facebook.authorize_redirect(redirect_uri)


def facebook_auth():
    token = current_user.oauth.facebook.authorize_access_token()
    resp = current_user.oauth.facebook.get(
        "https://graph.facebook.com/me?fields=id,name,email,picture{url}"
    )
    profile = resp.json()
    log(log.INFO, f"Profile:{profile}")
    return redirect("/")


def index():
    form = ChangePasswordForm(request.form)
    orders = Order.get_current_user_orders()
    return render_template("account/details.html", form=form, orders=orders)


def login():
    """login page."""
    form = LoginForm(request.form)
    if form.validate_on_submit():
        login_user(form.user)
        redirect_url = request.args.get("next") or url_for("public.home")
        flash(lazy_gettext("You are log in."), "success")
        return redirect(redirect_url)
    else:
        flash_errors(form)
    return render_template("account/login.html", form=form)


def id_generator(size=8, chars=string.ascii_uppercase + string.digits):
    return "".join(random.choice(chars) for _ in range(size))


def resetpwd():
    """Reset user password"""
    form = ResetPasswd(request.form)

    if form.validate_on_submit():
        flash(lazy_gettext("Check your e-mail."), "success")
        user = User.query.filter_by(email=form.username.data).first()
        new_passwd = id_generator()
        body = render_template("account/reser_passwd_mail.html", new_passwd=new_passwd)
        msg = Message(lazy_gettext("Reset Password"), recipients=[form.username.data])
        msg.body = lazy_gettext(
            """We cannot simply send you your old password.\n
        A unique password has been generated for you. Change the password after logging in.\n
        New Password is: %s"""
            % new_passwd
        )
        msg.html = body
        mail = current_app.extensions.get("mail")
        mail.send(msg)
        user.update(password=new_passwd)
        return redirect(url_for("account.login"))
    else:
        flash_errors(form)
    return render_template("account/login.html", form=form, reset=True)


@login_required
def logout():
    """Logout."""
    logout_user()
    flash(lazy_gettext("You are logged out."), "info")
    return redirect(url_for("public.home"))


def signup():
    """Register new user."""
    form = RegisterForm(request.form)
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data.lower(),
        )
        user.save()
        # send mail to the user
        msg = Message(
            subject="New password",
            sender=current_app.config["MAIL_DEFAULT_SENDER"],
            recipients=[user.email],
        )
        msg.html = render_template(
            "account/partials/email_confirmation.html",
            user=user,
            url=url_for(
                "account.set_password",
                reset_password_uid=user.reset_password_uid,
                _external=True,
            ),
            config=current_app.config,
        )
        current_app.mail.send(msg)
        flash(
            lazy_gettext(f"Confirmation email was sent to {form.email.data.lower()}"),
            "success",
        )
        return redirect(url_for("public.home"))
    else:
        flash_errors(form)
    return render_template("account/signup.html", form=form)


def set_password(reset_password_uid: str):
    user: User = User.query.filter(
        User.reset_password_uid == reset_password_uid
    ).first()

    if not user:
        log(log.ERROR, "wrong reset_password_uid. [%s]", reset_password_uid)
        flash("Incorrect reset password link", "danger")
        return redirect(url_for("account.index"))

    form = ChangePasswordForm(request.form)

    if form.validate_on_submit():
        user.password = form.password.data
        user.reset_password_uid = ""
        user.is_active = True
        user.save()
        login_user(user)
        flash("Login successful.", "success")
        return redirect(url_for("account.index"))
    elif form.is_submitted():
        log(log.WARNING, "form error: [%s]", form.errors)
        flash("Wrong user password.", "danger")
    return render_template(
        "account/password_reset.html", form=form, reset_password_uid=reset_password_uid
    )


def addresses():
    """List addresses."""
    addresses = current_user.addresses
    return render_template("account/addresses.html", addresses=addresses)


def edit_address():
    """Create and edit an address."""
    form = AddressForm(request.form)
    address_id = request.args.get("id", None, type=int)
    if address_id:
        user_address = UserAddress.get_by_id(address_id)
        form = AddressForm(request.form, obj=user_address)
    if request.method == "POST" and form.validate_on_submit():
        address_data = {
            "province": form.province.data,
            "city": form.city.data,
            "district": form.district.data,
            "address": form.address.data,
            "contact_name": form.contact_name.data,
            "contact_phone": form.contact_phone.data,
            "user_id": current_user.id,
        }
        if address_id:
            UserAddress.update(user_address, **address_data)
            flash(lazy_gettext("Success edit address."), "success")
        else:
            UserAddress.create(**address_data)
            flash(lazy_gettext("Success add address."), "success")
        return redirect(url_for("account.index") + "#addresses")
    else:
        flash_errors(form)
    return render_template(
        "account/address_edit.html", form=form, address_id=address_id
    )


def delete_address(id):
    user_address = UserAddress.get_by_id(id)
    if user_address in current_user.addresses:
        UserAddress.delete(user_address)
    return redirect(url_for("account.index") + "#addresses")


@impl
def flaskshop_load_blueprints(app):
    bp = Blueprint("account", __name__)
    google_bp = Blueprint("google", __name__)
    facebook_bp = Blueprint("facebook", __name__)

    google_bp.add_url_rule("/", view_func=google, methods=["GET", "POST"])
    google_bp.add_url_rule("/auth", view_func=google_auth, methods=["GET", "POST"])

    facebook_bp.add_url_rule("/", view_func=facebook, methods=["GET", "POST"])
    facebook_bp.add_url_rule("/auth/", view_func=facebook_auth, methods=["GET", "POST"])

    bp.add_url_rule("/", view_func=index)
    bp.add_url_rule("/login", view_func=login, methods=["GET", "POST"])
    bp.add_url_rule("/resetpwd", view_func=resetpwd, methods=["GET", "POST"])
    bp.add_url_rule("/logout", view_func=logout)
    bp.add_url_rule("/signup", view_func=signup, methods=["GET", "POST"])
    bp.add_url_rule(
        "/setpwd/<reset_password_uid>", view_func=set_password, methods=["GET", "POST"]
    )
    bp.add_url_rule("/address", view_func=addresses)
    bp.add_url_rule("/address/edit", view_func=edit_address, methods=["GET", "POST"])
    bp.add_url_rule(
        "/address/<int:id>/delete", view_func=delete_address, methods=["POST"]
    )

    app.register_blueprint(bp, url_prefix="/account")
    app.register_blueprint(google_bp, url_prefix="/google")
    app.register_blueprint(facebook_bp, url_prefix="/facebook")
