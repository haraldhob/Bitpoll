import csv
import datetime as dt
import re
import urllib.parse as parse
from datetime import timedelta
from decimal import Decimal

from bitpoll.base.models import BitpollUser
from bitpoll.caldav.utils import get_caldav
from bitpoll.invitations.models import Invitation
from bitpoll.poll.spam_util import (
    check_anti_spam_challange,
    create_anti_spam_challenge,
    get_spam_challenge_from_key,
)
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, F, Q, Sum, When
from django.http import HttpResponse, HttpResponseForbidden
from django.http.response import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.formats import date_format
from django.utils.timezone import activate as tz_activate
from django.utils.timezone import (
    get_current_timezone,
    localtime,
    make_aware,
    make_naive,
    now,
    utc,
)
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_POST
from django_token_bucket.models import TokenBucket
from pytz import all_timezones, timezone

from .forms import (
    ChoiceValueForm,
    CommentForm,
    DateChoiceCreationForm,
    DTChoiceCreationDateForm,
    DTChoiceCreationTimeForm,
    PollCopyForm,
    PollDeleteForm,
    PollSettingsForm,
)
from .models import (
    POLL_RESULTS,
    Choice,
    ChoiceValue,
    Comment,
    Poll,
    PollWatch,
    Vote,
    VoteChoice,
)


def poll(request, poll_url: str, reduced: str = None, export: bool = False):
    """
    :param export: if the view is exported to csv
    :param request
    :param poll_url: url of poll

    Displays for a given poll its fields along with all possible choices, all votes and all its comments.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    reduced_template = bool(reduced) or "reduced" in request.GET

    tz_activate(current_poll.get_tz_name(request.user))

    poll_votes = Vote.objects.filter(poll=current_poll).select_related("user")

    # Note: Reordering at this point is redundant, because poll votes and invitations are combined below and then
    # explicitly sorted.

    # if current_poll.sorting == Poll.ResultSorting.NAME:
    #     poll_votes = poll_votes.order_by('name')
    # elif current_poll.sorting == Poll.ResultSorting.DATE:
    #     poll_votes = poll_votes.order_by('date_created')
    # elif current_poll.sorting == Poll.ResultSorting.GROUP:
    #     # the desired behavior in this case is:
    #     # - stipendiaten appear first, ordered by name
    #     # - vertrauenspersonen appear second, also ordered by name
    #
    #     # this is kind of a hack to achieve the desired behavior:
    #     # I'm introducing an aggregated attribute called is_vertrauensperson by counting the number of groups assocaited
    #     # with a user that are named 'vertrauenspersonen'. Thus this attribute is 0 if the person who gave a vote is a
    #     # stip and 1 if they are a vertrauensperson
    #     poll_votes = poll_votes.annotate(
    #         is_vertrauensperson=Count(
    #             'user__groups',
    #             filter=Q(user__groups__name__iexact='vertrauenspersonen') # TODO extract the magic name into the config?
    #         )
    #     ).order_by('is_vertrauensperson', 'name')

    # prefetch_related('votechoice_set').select_releated() #TODO (Prefetch objekt nötig, wie ist der reverse join name wirklich?

    matrix = transpose(current_poll.get_choice_group_matrix(get_current_timezone()))

    # aggregate stats for all columns
    stats = (
        Choice.objects.filter(poll=current_poll, deleted=False)
        .order_by("sort_key")
        .annotate(score=Sum("votechoice__value__weight"))
        .values("score", "id", "text")
    )
    votes_count = poll_votes.count()

    invitations = current_poll.invitation_set.filter(vote=None)
    # The next block is limiting the visibility of the results
    summary = True
    if current_poll.require_login_view and not request.user.is_authenticated:
        params = {
            "next": reverse(
                "poll", args=[poll_url, "reduced"] if reduced_template else [poll_url]
            )
        }
        url_parts = list(parse.urlparse(django_settings.LOGIN_URL))
        query = dict(parse.parse_qsl(url_parts[4]))
        query.update(params)
        url_parts[4] = parse.urlencode(query)
        return HttpResponseRedirect(parse.urlunparse(url_parts))

    elif (
        current_poll.current_user_is_owner(request)
        and current_poll.show_results != "complete"
    ):
        messages.info(
            request, _("You can see the results because you are the owner of the Poll")
        )
    else:
        if current_poll.show_results in ("summary", "never"):
            if request.user.is_authenticated:
                poll_votes = poll_votes.filter(user=request.user)
                invitations = invitations.filter(user=request.user)
            else:
                poll_votes = []
                invitations = []
            messages.info(
                request, _("No individual results are shown due to Poll settings")
            )
        elif current_poll.show_results in (
            "summary after vote",
            "complete after vote",
        ) and (
            request.user.is_anonymous or not poll_votes.filter(Q(user=request.user))
        ):
            poll_votes = []
            messages.info(
                request, _("Results are only sown after (authenticated) Voting")
            )
            summary = False
        elif current_poll.show_results == "summary after vote":
            poll_votes = poll_votes.filter(user=request.user)
            messages.info(
                request, _("Only the Summary is shown due to the Poll settings")
            )
        if current_poll.show_results == "never":
            summary = False

    if not summary:
        messages.info(
            request, _("The summary is not shown due to the config of the Poll")
        )

    choices = (
        Choice.objects.filter(poll=current_poll, deleted=0)
        .select_related("poll")
        .order_by("sort_key")
    )
    vote_idx = {vote.id: i for (i, vote) in enumerate(poll_votes)}
    choice_idx = {choice.id: (i, choice) for (i, choice) in enumerate(choices)}

    vote_choice_matrix = [[None] * len(choice_idx) for bla in vote_idx]
    for vote_choice in VoteChoice.objects.filter(
        vote__poll=current_poll, choice__deleted=0
    ).select_related("value"):
        if vote_choice.vote_id in vote_idx:
            x = vote_idx[vote_choice.vote_id]
            y, choice = choice_idx[vote_choice.choice_id]
            vote_choice_matrix[x][y] = {
                "comment": vote_choice.comment,
                "value": vote_choice.value,
                "choice": choice,
            }

    voted_entries = map(lambda x: ("VOTE", x), zip(poll_votes, vote_choice_matrix))
    invited_entries = map(lambda x: ("INVITE", x), invitations)
    all_entries = list(voted_entries) + list(invited_entries)

    def getkey_vote_and_invitation(item):
        type, item = item
        if type == "INVITE":
            if current_poll.sorting == Poll.ResultSorting.NAME:
                return item.user.username
            elif current_poll.sorting == Poll.ResultSorting.DATE:
                return item.date_created
            elif current_poll.sorting == Poll.ResultSorting.GROUP:
                for i, group in enumerate(django_settings.POLL_GROUP_ORDERING):
                    if len(item.user.groups.filter(name=group).all()) > 0:
                        return (i, item.user.username)
                return (len(django_settings.POLL_GROUP_ORDERING), item.user.username)
        elif type == "VOTE":
            vote, _ = item

            # anonymous votes don't have an associated user
            if vote.user is None:
                return (len(django_settings.POLL_GROUP_ORDERING), "Anonymous")

            if current_poll.sorting == Poll.ResultSorting.NAME:
                return vote.user.username
            elif current_poll.sorting == Poll.ResultSorting.DATE:
                return vote.date_created
            elif current_poll.sorting == Poll.ResultSorting.GROUP:
                for i, group in enumerate(django_settings.POLL_GROUP_ORDERING):
                    if len(vote.user.groups.filter(name=group).all()) > 0:
                        return (i, vote.user.username)
                return (len(django_settings.POLL_GROUP_ORDERING), vote.user.username)

        return (len(django_settings.POLL_GROUP_ORDERING) + 1, "")

    all_entries.sort(key=getkey_vote_and_invitation)
    # keys = map(getkey_vote_and_invitation, vote_entries)

    # aggregate stats for the different Choice_Values per column

    stats2 = (
        Choice.objects.filter(poll=current_poll, deleted=False)
        .order_by("sort_key")
        .annotate(count=Count("votechoice__value__color"))
        .values(
            "count",
            "id",
            "votechoice__value__icon",
            "votechoice__value__color",
            "votechoice__value__title",
            "votechoice__value__deleted",
        )
    )
    #
    # use average for stats
    stats = [
        {
            "score": (stat["score"] / Decimal(votes_count) if votes_count > 0 else 0)
            if stat["score"] is not None
            else None,
            "count": stat["score"],
            "text": stat,
            "choices": [
                {
                    "count": stat2["count"],
                    "color": stat2["votechoice__value__color"],
                    "icon": stat2["votechoice__value__icon"],
                    "deleted": stat2["votechoice__value__deleted"],
                    "title": stat2["votechoice__value__title"],
                }
                for stat2 in stats2
                if stat2["id"] == stat["id"]
                and stat2["votechoice__value__color"] != None
            ],
        }
        for stat in stats
    ]

    if (
        current_poll.current_user_is_owner(request)
        and current_poll.allow_unauthenticated_vote_changes
    ):
        messages.warning(
            request,
            _(
                "Currently, unauthenticated users are allowed to change votes. This means, "
                "that everyone is able to change every vote that has not been assigned to a user. "
                "If you want to prevent this, change the settings."
            ),
        )

    if request.user.is_authenticated:
        # warn the user if the Timezone is not the same on the Poll and in his settings
        different_timezone = current_poll.timezone_name != request.user.timezone
        if current_poll.use_user_timezone and different_timezone:
            messages.info(
                request,
                _(
                    "This poll was transferred from {} to your local timezone {}".format(
                        current_poll.timezone_name, request.user.timezone
                    )
                ),
            )
        elif different_timezone:
            messages.warning(
                request,
                _(
                    "This poll has a different timezone ({}) than you.".format(
                        current_poll.timezone_name
                    )
                ),
            )

    deleted_choicevals_count = VoteChoice.objects.filter(
        choice__poll=current_poll, value__deleted=True
    ).count()
    if deleted_choicevals_count > 0:
        messages.warning(
            request,
            _(
                "Some votes contain deleted values. If you have already voted, please check your "
                "vote."
            ),
        )

    max_score = None
    if stats and votes_count > 0:
        max_score_list = [val["score"] for val in stats if val["score"] is not None]
        if max_score_list:
            max_score = max(max_score_list)

    if export:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="poll.csv"'
        writer = csv.writer(response)
        a = [choice.get_title for choice in current_poll.ordered_choices]
        row = ["Name", "Email", "Groups", "Datetime", "Comment"]
        row.extend(a)
        writer.writerow(row)
        for type, entry in all_entries:
            if type == "VOTE":
                vote, votechoices = entry
                row = [
                    vote.display_name
                    if not current_poll.hide_participants
                    else _("Hidden")
                ]
                row.append(vote.user.email)
                # filter the user's groups to show only those that are in the whitelist for the tooltip
                row.append(
                    ", ".join(
                        set(django_settings.POLL_GROUP_HOVER_WHITELIST)
                        & set(map(lambda g: g.name, vote.user.groups.all()))
                    )
                )
                row.append(vote.date_created.isoformat(timespec="seconds"))
                row.append(vote.comment if vote.comment else "")
                row.extend(
                    [
                        (
                            choice["value"].title
                            + (
                                " ({})".format(choice["comment"])
                                if choice
                                and choice["comment"]
                                and len(choice["comment"]) > 0
                                else ""
                            )
                        )
                        if choice and choice["value"]
                        else ""
                        for choice in votechoices
                    ]
                )
                writer.writerow(row)
            elif type == "INVITE":
                invitation = entry
                row = [
                    invitation.user.get_displayname()
                    if not current_poll.hide_participants
                    else _("Hidden")
                ]
                row.append(invitation.user.email)
                # filter the user's groups to show only those that are in the whitelist for the tooltip
                row.append(
                    ", ".join(
                        set(django_settings.POLL_GROUP_HOVER_WHITELIST)
                        & set(map(lambda g: g.name, invitation.user.groups.all()))
                    )
                )
                row.append(_("Invited but didn't participate"))
                row.extend(["" for _ in range(len(a) + 1)])
                writer.writerow(row)
        return response

    return TemplateResponse(
        request,
        "poll/poll.html",
        {
            "basetemplate_name": "base.html"
            if not reduced_template
            else "base_reduced.html",
            "poll": current_poll,
            "matrix": matrix,
            # 'choices_matrix': zip(matrix, current_poll.choice_set.all()),
            "page": "",
            "vote_entries": all_entries,
            "stats": stats,
            "max_score": max_score,
            # 'invitations': invitations if current_poll.show_invitations else [],
            "summary": summary,
            "comment_form": CommentForm(),
            "comments": current_poll.comment_set.order_by("-date_created"),
            "choice_values": ChoiceValue.objects.filter(poll=current_poll),
            "spam_challenge": create_anti_spam_challenge(current_poll.id),
            "url_append": "" if not reduced_template else "?reduced",
        },
    )


def comment(request, poll_url, comment_id=None):
    """
    Post a comment to a poll
    :param request:
    :param poll_url: the poll url to post to
    :param comment_id:
    :return:
    """

    reduced_template = True if "reduced" in request.GET else False
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.allow_comments:
        messages.error(request, _("Comments are disabled for this Poll"))
        response = redirect("poll", poll_url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response
    user = None
    if not request.user.is_anonymous:
        user = request.user
    if request.POST:
        form = CommentForm(request.POST)
        if form.is_valid():
            token_bucket = TokenBucket.get(
                "Comments", current_poll, 5, 1800, "commenting"
            )
            try:
                spam_ok = True
                if not user:
                    if (
                        "spam_answer" in form.cleaned_data
                        and "spam_key" in form.cleaned_data
                    ):
                        spam_ok = check_anti_spam_challange(
                            form.cleaned_data["spam_key"],
                            form.cleaned_data["spam_answer"],
                            current_poll.id,
                        )
                    else:
                        spam_ok, err_message = False, _("This Field is rquired")
                text = form.cleaned_data["text"]
                name = form.cleaned_data["name"]
                spam_challenge = get_spam_challenge_from_key(
                    form.cleaned_data["spam_key"], current_poll.id
                )
                if spam_ok:
                    if not user:
                        token_bucket.consume(1)
                    if user or name:
                        if user:
                            name = user.get_displayname()
                        if comment_id:
                            comment_obj = get_object_or_404(Comment, pk=comment_id)
                            if comment_obj.can_edit(request.user):
                                comment_obj.text = text
                                # comment.name = name # TODO: wenn wir das erlauben wollen mit angemeldet/nicht angemeldet aufpassen
                                # das die namen nicht durcheinander kommen.
                                comment_obj.save()
                            else:
                                messages.error(
                                    request, _("You can't edit this Comment")
                                )
                        else:
                            new_comment = Comment(
                                text=text,
                                date_created=now(),
                                name=name,
                                poll=current_poll,
                                user=user,
                            )
                            new_comment.save()
                        response = redirect("poll", poll_url)
                        if reduced_template:
                            response["Location"] += "?reduced"
                        return response
                    else:
                        form.add_error("name", _("Provide a name"))
                else:
                    form.add_error("spam_answer", _("Wrong result"))
            except token_bucket.TokensExceeded as e:
                form.add_error(None, e)
                spam_challenge = get_spam_challenge_from_key(
                    form.cleaned_data["spam_key"], current_poll.id
                )
            except ValidationError as e:
                # if the anti spam challenge faild we generate a new one.
                spam_challenge = create_anti_spam_challenge(current_poll.id)
                form.add_error("spam_answer", e.message)
        else:
            if "spam_key" in request.POST:
                spam_challenge = get_spam_challenge_from_key(
                    form.cleaned_data["spam_key"], current_poll.id
                )
            else:
                spam_challenge = create_anti_spam_challenge(current_poll.id)
    else:
        if comment_id:
            comment_obj = get_object_or_404(Comment, pk=comment_id)
            if comment_obj.can_edit(request.user):
                form = CommentForm(instance=comment_obj)
            else:
                messages.error(request, _("You can't edit this Comment"))
                response = redirect("poll", poll_url)
                if reduced_template:
                    response["Location"] += "?reduced"
                return response
        else:
            form = CommentForm()
        spam_challenge = create_anti_spam_challenge(current_poll.id)

    return TemplateResponse(
        request,
        "poll/comment_edit.html",
        {
            "basetemplate_name": "base.html"
            if not reduced_template
            else "base_reduced.html",
            "url_append": "" if not reduced_template else "?reduced",
            "comment_form": form,
            "comment_edit_id": comment_id,
            "poll": current_poll,
            "spam_challenge": spam_challenge,
        },
    )


def delete_comment(request, poll_url, comment_id):
    """
    :param request:
    :param poll_url: url of poll belonging to comment
    :param comment_id: ID of comment to be deleted
    :return:

    Case Delete:
        If the user is authenticated and equal to the saved user of the comment, the comment is deleted
        and the user is directed back to the poll's page

        If the user is authenticated but differs from the saved user of the comment, the user is directed
        back with error message "Deletion not allowed. You are not [comment.name]"

        Without authentication the user is directed back with error message "Deletion not allowed.
        You are not authenticated."

    Case Cancel:
        The user is redirected back to the poll's page.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    current_comment = get_object_or_404(Comment, id=comment_id)
    error_msg = ""
    reduced_template = True if "reduced" in request.GET else False

    if request.method == "POST":
        if "Delete" in request.POST:
            if request.user.is_authenticated:
                # TODO additional possibilities of deleting
                if current_comment.can_delete(request.user):
                    current_comment.delete()
                    response = redirect("poll", poll_url)
                    if reduced_template:
                        response["Location"] += "?reduced"
                    return response
                else:
                    error_msg = _(
                        "Deletion not allowed. You are not {}.".format(
                            str(current_comment.name)
                        )
                    )
            else:
                error_msg = _("Deletion not allowed. You are not authenticated.")
        else:
            response = redirect("poll", poll_url)
            if reduced_template:
                response["Location"] += "?reduced"
            return response

    reduced_template = True if "reduced" in request.GET else False

    return TemplateResponse(
        request,
        "poll/comment_delete.html",
        {
            "basetemplate_name": "base.html"
            if not reduced_template
            else "base_reduced.html",
            "url_append": "" if not reduced_template else "?reduced",
            "poll": current_poll,
            "comment": current_comment,
            "error": error_msg,
        },
    )


@require_POST
@login_required
def watch(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    reduced_template = True if "reduced" in request.GET else False

    if not current_poll.can_watch(request.user):
        messages.error(request, _("You are not allowed to watch this poll."))
        response = redirect("poll", poll_url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response

    if current_poll.user_watches(request.user):
        poll_watch = PollWatch.objects.get(poll=current_poll, user=request.user)
        poll_watch.delete()
    else:
        poll_watch = PollWatch(poll=current_poll, user=request.user)
        poll_watch.save()
    response = redirect("poll", poll_url)
    if reduced_template:
        response["Location"] += "?reduced"
    return response


def edit_choice(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    reduced_template = True if "reduced" in request.GET else False

    if not current_poll.can_edit(request.user, request):
        response = redirect("poll", poll_url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response

    if current_poll.type == "universal":
        response = redirect("poll_editUniversalChoice", current_poll.url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response
    elif current_poll.type == "date":
        response = redirect("poll_editDateChoice", current_poll.url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response
    else:
        response = redirect("poll_editDTChoiceDate", current_poll.url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response
    pass


def edit_date_choice(request, poll_url):
    """
    :param request:
    :param poll_url: url of poll

    Takes several dates as the user's input und checks the validity.
    If the input is valid, for every given date a choice is created and saved. The user is directed to the poll's site.

    If the input is not valid, the user is directed back for correction.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    tz_activate("UTC")
    initial = {
        "dates": ",".join(
            set(
                list(
                    date_format(localtime(c.date), format="Y-m-d")
                    for c in current_poll.choice_set.filter(deleted=False).order_by(
                        "sort_key"
                    )
                )
            )
        ),
    }
    if request.method == "POST":
        form = DateChoiceCreationForm(request.POST, initial=initial)
        if form.is_valid():
            choices = current_poll.choice_set.all()
            # List of the Old Ids, used for detection what has to be deleted
            old_choices_ids = [c.pk for c in choices]
            new_choices = []
            old_choices = []
            dates = []
            error = False
            # clean the data
            for choice in form.cleaned_data["dates"].split(","):
                try:
                    tz = timezone("UTC")
                    parsed_date = parse_datetime("{} 0:0".format(choice))
                    if parsed_date:
                        date = tz.localize(parsed_date)
                        dates.append(date)
                    else:
                        error = True
                        messages.error(
                            _(
                                "There was en error interpreting the provided dates and times"
                            )
                        )
                except ValueError:
                    # This will most likely only happen with users turning of JS
                    error = True
                    messages.error(
                        _(
                            "There was en error interpreting the provided dates and times"
                        )
                    )
            if not error:
                for i, datum in enumerate(sorted(dates)):
                    choice_objs = Choice.objects.filter(poll=current_poll, date=datum)
                    if choice_objs:
                        choice_obj = choice_objs[0]
                        old_choices_ids.remove(choice_obj.pk)
                        choice_obj.sort_key = i
                        choice_obj.deleted = False
                        old_choices.append(choice_obj)
                    else:
                        new_choices.append(
                            Choice(text="", date=datum, poll=current_poll, sort_key=i)
                        )
                with transaction.atomic():
                    Choice.objects.bulk_create(new_choices)
                    for choice in old_choices:
                        choice.save()
                    Choice.objects.filter(pk__in=old_choices_ids).update(deleted=True)
                date_choices = {
                    date_choice.date.date().isoformat(): date_choice.text
                    for date_choice in (new_choices + old_choices)
                }
                return TemplateResponse(
                    request,
                    "poll/choice_creation_date_labels.html",
                    {
                        "dates": date_choices,
                        "poll": current_poll,
                        "page": "Choices",
                        "step": 2,
                    },
                )
    else:
        form = DateChoiceCreationForm(initial=initial)
    return TemplateResponse(
        request,
        "poll/choice_creation_date.html",
        {
            "poll": current_poll,
            "new_choice": form,
            "page": "Choices",
            "step": 1,
            "is_dt_choice": False,
        },
    )


def edit_choice_date_labels(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    if request.method == "POST":
        changed_choices = []
        for key in request.POST.keys():
            if key.startswith("label_"):
                if date := parse_date(key.replace("label_", "")):
                    datetime_date = utc.localize(
                        dt.datetime.combine(date, dt.time(0, 0))
                    )
                    choice_filter = current_poll.choice_set.filter(date=datetime_date)
                    if choice_filter.exists():
                        choice = choice_filter.first()
                        choice.text = request.POST.get(key)
                        changed_choices.append(choice)

        # Save new choices to database, Update/Delete old ones
        with transaction.atomic():
            for choice in changed_choices:
                choice.save()
        return redirect("poll", current_poll.url)
    return redirect("poll_editDateChoice", current_poll.url)


def edit_dt_choice_date(request, poll_url):
    """
    :param request:
    :param poll_url: url of poll

    Takes several dates as the user's input and checks if it's valid.
    If the data is valid, the user is directed to the time-input-site. (The date is passed on as an argument)

    If the data is not valid, the user is directed back for correction.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    tz_activate(current_poll.timezone_name)
    initial = {
        "dates": ",".join(
            set(
                list(
                    date_format(localtime(c.date), format="Y-m-d")
                    for c in current_poll.choice_set.filter(deleted=False).order_by(
                        "sort_key"
                    )
                )
            )
        ),
        "times": ",".join(
            set(
                list(
                    date_format(localtime(c.date), format="H:i")
                    for c in current_poll.choice_set.filter(deleted=False).order_by(
                        "sort_key"
                    )
                )
            )
        ),
    }
    form = DTChoiceCreationDateForm(initial=initial)
    if request.method == "POST":
        form = DTChoiceCreationDateForm(request.POST, initial=initial)
        if form.is_valid():
            initial["dates"] = form.cleaned_data.get("dates")
            time = DTChoiceCreationTimeForm(initial=initial)
            return TemplateResponse(
                request,
                "poll/dt_choice_creation_time.html",
                {
                    "time": time,
                    "poll": current_poll,
                    "page": "Choices",
                    "step": 2,
                },
            )
    return TemplateResponse(
        request,
        "poll/choice_creation_date.html",
        {
            "new_choice": form,
            "poll": current_poll,
            "step": 1,
            "page": "Choices",
            "is_dt_choice": True,
        },
    )


def edit_dt_choice_time(request, poll_url):
    """
    :param request:
    :param poll_url: url of poll

    Takes several times as the user's input and checks the validity.
    If the data is valid, the user is directed to the combinations-site, to which all possible combinations of
        dates and times are passed on.
    If the dates are missing, the user is directed back to the date-input-site.
    If the times are missing, the user is directed back to the time-input-site.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    tz_activate(current_poll.timezone_name)
    initial = {
        "dates": ",".join(
            date_format(localtime(c.date), format="Y-m-d")
            for c in current_poll.choice_set.filter(deleted=False).order_by("sort_key")
        ),
        "times": ",".join(
            set(
                list(
                    date_format(localtime(c.date), format="H:i")
                    for c in current_poll.choice_set.filter(deleted=False).order_by(
                        "sort_key"
                    )
                )
            )
        ),
    }
    if request.method == "POST":
        form = DTChoiceCreationTimeForm(request.POST, initial=initial)
        if form.is_valid():
            times = form.cleaned_data["times"].split(",")
            dates = form.cleaned_data["dates"].split(",")

            date_choices = {
                date_choice.date.date().isoformat(): date_choice.text
                for date_choice in current_poll.choice_set.filter(deleted=False)
                if date_choice.date.date().isoformat() in dates
            }
            for date in dates:
                date_choices.setdefault(date, "")

            initial_choices = current_poll.choice_set.filter(deleted=False).values_list(
                "date"
            )
            initial_choices = list(initial_choices)
            initial_choices = [
                (
                    date_format(localtime(elem[0]), format="Y-m-d"),
                    date_format(localtime(elem[0]), format="H:i"),
                )
                for elem in initial_choices
            ]

            return TemplateResponse(
                request,
                "poll/dt_choice_creation_combinations.html",
                {
                    "times": times,
                    "dates": date_choices,
                    "initial_choices": initial_choices,
                    "poll": current_poll,
                    "page": "Choices",
                    "step": 3,
                },
            )
        elif form.cleaned_data["dates"] != "":
            return TemplateResponse(
                request,
                "poll/dt_choice_creation_time.html",
                {
                    "time": form,
                    "poll": current_poll,
                    "page": "Choices",
                    "step": 2,
                },
            )
    return redirect("poll_editDTChoiceDate", current_poll.url)


def edit_dt_choice_combinations(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    tz_activate(current_poll.timezone_name)
    initial_choices = current_poll.choice_set.filter(deleted=False).values_list("date")
    initial_choices = list(initial_choices)
    initial_choices = [
        (
            date_format(localtime(elem[0]), format="Y-m-d"),
            date_format(localtime(elem[0]), format="H:i"),
        )
        for elem in initial_choices
    ]

    if request.method == "POST":
        # getlist does not raise an exception if datetimes[] is not in request.POST
        chosen_combinations = request.POST.getlist("datetimes[]")

        chosen_times = []
        new_choices = []
        old_choices = []
        choices = current_poll.choice_set.all()
        # List of the Old Ids, used for detection what has to be deleted
        old_choices_ids = [c.pk for c in choices]
        # parse datetime objects of chosen combinations
        for combination in chosen_combinations:
            try:
                tz = timezone(current_poll.timezone_name)
                timestamp = parse_datetime(combination)
                if timestamp:
                    chosen_times.append(tz.localize(timestamp))
                else:
                    messages.error(
                        request,
                        _(
                            "There was en error interpreting the provided dates and times"
                        ),
                    )
                    return redirect("poll_editDTChoiceDate", current_poll.url)
            except ValueError:
                # at least one invalid time/date has been specified. Redirect to first step # TODO: error message spezifizierne
                messages.error(
                    request,
                    _("There was en error interpreting the provided dates and times"),
                )
                return redirect("poll_editDTChoiceDate", current_poll.url)
        # Search for already existing Choices
        for i, date_time in enumerate(sorted(chosen_times)):
            choice_obj = current_poll.choice_set.filter(date=date_time)
            if choice_obj:
                old_choices_ids.remove(choice_obj[0].pk)
                choice_obj[0].sort_key = i
                choice_obj[0].deleted = False  # Mark as not deleted
                old_choices.append(choice_obj[0])
            else:
                new_choices.append(
                    Choice(date=date_time, poll=current_poll, sort_key=i)
                )

        for key in request.POST.keys():
            if key.startswith("label_"):
                if date := parse_date(key.replace("label_", "")):
                    for choice in new_choices + old_choices:
                        if choice.date.date() == date:
                            choice.text = request.POST.get(key)

        # Save new choices to database, Update/Delete old ones
        with transaction.atomic():
            # Save the new Choices
            Choice.objects.bulk_create(new_choices)
            for choice in old_choices:
                choice.save()
            Choice.objects.filter(pk__in=old_choices_ids).update(deleted=True)
        return redirect("poll", current_poll.url)
    return redirect("poll_editDTChoiceDate", current_poll.url)


def edit_universal_choice(request, poll_url):
    """
    :param request:
    :param poll_url: url of poll

    Takes the text of a choice as the user's input and checks its validity.
    If the input is valid, the choice is saved and the user is directed to the poll's site.

    If the input is not valid, the user is directed back for correction.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    if request.method == "POST":
        # save new choices
        choice_texts = request.POST.getlist("choice_text")
        choice_sort_keys = request.POST.getlist(
            "choice_sort_key"
        )  # TODO: errorhandling
        error = False
        for i, choice_text in zip(choice_sort_keys, choice_texts):
            choice_text = choice_text.strip()
            if choice_text == "":
                continue
            choice = Choice(text=choice_text, poll=current_poll, sort_key=i)
            try:
                choice.full_clean()
                choice.save()
            except ValidationError:
                messages.error(
                    request,
                    _(
                        'The title "{}" is to long. The maximum is 80 characters'.format(
                            choice_text
                        )
                    ),
                )
                error = True
                # TODO: reentry text in form? / Use normal ModelForm?

        # update existing choices
        pattern = re.compile(r"^choice_text_(\d+)$")
        with transaction.atomic():
            for choice_id in request.POST.keys():
                choice = pattern.match(choice_id)
                if not choice:
                    continue
                pk = choice.group(1)
                db_choice = get_object_or_404(Choice, poll=current_poll, pk=pk)
                choice_text = request.POST.get(choice_id).strip()
                if choice_text == "":
                    db_choice.deleted = True
                else:
                    db_choice.text = choice_text
                    sort_key = request.POST.get("choice_sort_key_{}".format(pk), -1)
                    if sort_key == -1 or sort_key == "":
                        sort_key = (
                            current_poll.choice_set.count() + 1
                        )  # TODO: unter umständen hier max nemen?
                    db_choice.sort_key = sort_key
                    try:
                        db_choice.full_clean()
                        db_choice.save()
                    except ValidationError:
                        # TODO: können hier auch andere fehler auftreten?
                        # TODO: reentry text in form? / Use normal ModelForm?
                        messages.error(
                            request,
                            _(
                                'The title "{}" is to long. The maximum is 80 characters'.format(
                                    choice_text
                                )
                            ),
                        )
                        error = True
        if "next" in request.POST and not error:
            return redirect("poll", poll_url)
        if "delete" in request.POST:
            db_choice = get_object_or_404(
                Choice, poll=current_poll, pk=request.POST.get("delete")
            )
            db_choice.deleted = not db_choice.deleted
            db_choice.save()

    return TemplateResponse(
        request,
        "poll/universal_choice_creation.html",
        {
            "choices": current_poll.choice_set.all().order_by("sort_key"),
            "poll": current_poll,
            "page": "Choices",
            "next_sort_key": current_poll.choice_set.count()
            + 1,  # TODO: unter umständen hier max nemen?
        },
    )


def edit_choicevalues(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    choiceval_select = None
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    form = ChoiceValueForm()
    if request.method == "POST":
        if "delete" in request.POST:
            choiceval_id = request.POST.get("delete", None)
            if choiceval_id:
                choiceval = get_object_or_404(ChoiceValue, id=choiceval_id)
                choiceval.deleted = True
                choiceval.save()
            return redirect("poll_editchoicevalues", current_poll.url)

        if "restore" in request.POST:
            choiceval_id = request.POST.get("restore", None)
            if choiceval_id:
                choiceval = get_object_or_404(ChoiceValue, id=choiceval_id)
                choiceval.deleted = False
                choiceval.save()
            return redirect("poll_editchoicevalues", current_poll.url)

        elif "edit" in request.POST:
            choiceval_id = request.POST.get("edit", None)
            if choiceval_id:
                choiceval_select = get_object_or_404(ChoiceValue, id=choiceval_id)
                form = ChoiceValueForm(instance=choiceval_select)

    return TemplateResponse(
        request,
        "poll/choicevalue.html",
        {
            "poll": current_poll,
            "form": form,
            "choiceval_select": choiceval_select,
            "choice_values": current_poll.choicevalue_set.order_by("-weight", "title"),
        },
    )


@require_POST
def edit_choicevalues_create(request, poll_url):
    current_poll = get_object_or_404(Poll, url=poll_url)
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    form = ChoiceValueForm(request.POST)
    if form.is_valid():
        title = form.cleaned_data["title"]
        color = form.cleaned_data["color"]
        icon = form.cleaned_data["icon"]
        weight = form.cleaned_data["weight"]
        current_id = request.POST.get("choiceval_id", None)

        if current_id:
            current_choiceval = get_object_or_404(
                ChoiceValue, id=current_id, poll=current_poll
            )
            current_choiceval.title = title
            current_choiceval.color = color
            current_choiceval.icon = icon
            current_choiceval.weight = weight

            current_choiceval.save()
        else:
            choice_val = ChoiceValue(
                title=title, icon=icon, color=color, weight=weight, poll=current_poll
            )
            choice_val.save()
    else:
        choiceval_id = request.POST.get("choiceval_id", None)
        if choiceval_id:
            choiceval_select = get_object_or_404(ChoiceValue, id=choiceval_id)
        else:
            choiceval_select = None
        return TemplateResponse(
            request,
            "poll/choicevalue.html",
            {
                "poll": current_poll,
                "form": form,
                "choiceval_select": choiceval_select,
                "choice_values": current_poll.choicevalue_set.order_by(
                    "-weight", "title"
                ),
            },
        )
    return redirect("poll_editchoicevalues", current_poll.url)


def delete(request, poll_url):
    """
    :param request:
    :param poll_url: url of poll to be deleted
    :return:

    Given Poll is deleted if delete-button is pressed and if user is authenticated.
    Otherwise the user is directed back to the poll's page.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    error_msg = ""

    if request.method == "POST":
        if "Delete" in request.POST:
            if request.user.is_authenticated:
                # TODO restriction for deletion same as edit?
                if current_poll.can_edit(request.user, request):
                    current_poll.delete()
                return redirect("index")
            else:
                error_msg = _("Deletion not allowed. You are not authenticated.")
        else:
            return redirect("poll", poll_url)

    form = PollDeleteForm(instance=current_poll)

    return TemplateResponse(
        request,
        "poll/poll_delete.html",
        {
            "poll": current_poll,
            "form": form,
            "error": error_msg,
        },
    )


def vote(request, poll_url, vote_id=None):
    """
    :param request:
    :param poll_url: Url of poll
    :param vote_id: Optional the voteID to edit
    :return:

    Takes vote with comments as input and saves the vote along with all comments.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    reduced_template = True if "reduced" in request.GET else False
    error_msg = False
    deleted_choicevals = False
    expired_choices = False

    if current_poll.due_date and current_poll.due_date < now():
        messages.error(
            request, _("This Poll is past the due date, voting is no longer possible")
        )
        response = redirect("poll", poll_url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response

    if not current_poll.can_vote(request.user, request, vote_id is not None):
        if current_poll.require_login and not request.user.is_authenticated:
            raise Exception()
            return redirect_to_login(
                reverse("poll_vote", args=[poll_url]) + f"?next={poll_url}"
            )
        else:
            response = redirect("poll", poll_url)
            if reduced_template:
                response["Location"] += "?reduced"
            return response

    tz_activate(current_poll.get_tz_name(request.user))

    allow_edit_hours = (
        django_settings.POLL_ALLOW_EDIT_DAYS * 24 + 24
    )  # the +24 is because date polls are always defined
    # at 00:00, and thus the 'effective' allowed time to edit after a poll has passed is one day less than given.
    only_choices_after = None
    if (
        current_poll.type == "datetime" or current_poll.type == "date"
    ) and not current_poll.change_vote_after_event:
        only_choices_after = now() - timedelta(hours=allow_edit_hours)
        only_choices_after = utc.localize(
            dt.datetime.combine(only_choices_after.date(), dt.time(0, 0))
        )

    if request.method == "POST":
        vote_id = request.POST.get("vote_id", None)
        if vote_id:
            current_vote = get_object_or_404(Vote, pk=vote_id, poll=current_poll)
            if not current_vote.can_edit(request.user):
                # the vote belongs to an user and it is not the authenticated user
                return HttpResponseForbidden()  # todo: better errorpage?
        else:
            current_vote = Vote(poll=current_poll)
        current_vote.date_created = now()
        current_vote.comment = request.POST.get("comment")
        if vote_id:
            # leave the name as it was
            pass
        elif "anonymous" in request.POST:
            current_vote.name = "Anonymous"
        elif request.user.is_authenticated:
            current_vote.name = request.user.get_displayname()
            current_vote.user = request.user

            if request.user.auto_watch:
                try:
                    poll_watch = PollWatch(poll=current_poll, user=request.user)
                    poll_watch.save()
                except IntegrityError:
                    pass
        else:
            current_vote.name = request.POST.get("name").strip()

        if len(current_vote.name) > 80:
            messages.error(
                request,
                _("The Name is longer than the allowed name length of 80 characters"),
            )
            response = redirect("poll", poll_url)
            if reduced_template:
                response["Location"] += "?reduced"
            return response  # todo: das macht keinen sinn, warum nicht verbessern?

        current_vote.anonymous = "anonymous" in request.POST

        if not current_poll.anonymous_allowed and current_vote.anonymous:
            messages.error(request, _("Anonymous votes are not allowed for this poll."))
        else:
            if current_vote.anonymous or current_vote.name:
                # prevent non-anonymous vote without name
                try:
                    with transaction.atomic():
                        new_choices = []

                        current_vote.save()

                        if request.user.is_authenticated:
                            # check if this user was invited
                            invitation = current_poll.invitation_set.filter(
                                user=request.user
                            )
                            if invitation:
                                invitation = invitation[0]
                                invitation.vote = current_vote
                                invitation.save()

                        for choice in current_poll.choice_set.all():
                            if (
                                str(choice.id) in request.POST
                                and request.POST[str(choice.id)].isdecimal()
                            ):
                                choice_value = get_object_or_404(
                                    ChoiceValue, id=request.POST[str(choice.id)]
                                )
                                if not choice_value.deleted:
                                    if (
                                        not (
                                            current_poll.type == "datetime"
                                            or current_poll.type == "date"
                                        )
                                        or current_poll.change_vote_after_event
                                        or choice.date > only_choices_after
                                    ):
                                        new_choices.append(
                                            VoteChoice(
                                                value=choice_value,
                                                vote=current_vote,
                                                choice=choice,
                                                comment=request.POST.get(
                                                    "comment_{}".format(choice.id)
                                                )
                                                or "",
                                            )
                                        )
                                    else:
                                        expired_choices = True
                                else:
                                    deleted_choicevals = True
                            else:
                                if current_poll.vote_all and not choice.deleted:
                                    if (
                                        not error_msg
                                    ):  # TODO: error_msg is used in other places here to, maybe use
                                        # deduplication for messages?
                                        # https://stackoverflow.com/questions/23249807/django-remove-duplicate
                                        # -messages-from-storage
                                        messages.error(
                                            request,
                                            _(
                                                "Due to the the configuration of this poll, "
                                                "you have to fill all choices."
                                            ),
                                        )
                                    error_msg = True

                        if deleted_choicevals:
                            error_msg = True
                            messages.error(
                                request,
                                _(
                                    "Value for choice does not exist. This is probably due to "
                                    "changes in the poll. Please correct your vote."
                                ),
                            )
                        if expired_choices:
                            error_msg = True
                            messages.error(
                                request,
                                _(
                                    "Tried to vote for a choice that has expired. "
                                    "This is probably because the poll's settings were changed"
                                    "since you started voting. Please reload the page."
                                ),
                            )  # TODO translate

                        if not error_msg:
                            if vote_id:
                                if current_poll.change_vote_after_event:
                                    VoteChoice.objects.filter(
                                        vote=current_vote
                                    ).delete()
                                else:
                                    VoteChoice.objects.filter(
                                        vote=current_vote,
                                        choice__date__gte=only_choices_after,
                                    ).delete()
                                # todo: nochmal prüfen ob das wirjklich das tut was es soll, also erst alles löschen und dann neu anlegen
                                # todo eventuell eine transaktion drum machen? wegen falls das eventuell dazwischen abbricht?
                            else:
                                for current_watch in current_poll.pollwatch_set.all():
                                    current_watch.send(
                                        request=request, vote=current_vote
                                    )

                            VoteChoice.objects.bulk_create(new_choices)
                            messages.success(request, _("Vote has been recorded"))
                            response = redirect("poll", poll_url)
                            if reduced_template:
                                response["Location"] += "?reduced"
                            return response
                        else:
                            raise IntegrityError(
                                "An Error while saving the Vote occurred, see message"
                            )
                except IntegrityError as e:
                    # Nothing todo as the main point in this exception is the database rollback
                    pass
            else:
                messages.error(
                    request,
                    _("You need to either provide a name or post an anonymous vote."),
                )

    # no/invalid POST: show the dialog
    matrix = current_poll.get_choice_group_matrix(
        get_current_timezone(), choices_after=only_choices_after
    )
    if len(matrix) == 0 or matrix == [[]]:
        messages.error(
            request,
            _("Voting time for all options has expired, voting is no longer possible"),
        )
        response = redirect("poll", poll_url)
        if reduced_template:
            response["Location"] += "?reduced"
        return response
    if len(matrix) < len(current_poll.ordered_choices):
        messages.info(
            request,
            _(
                "Some poll options have already passed. You will not be able to change your vote for these options."
            ),
        )
    choices = []
    comments = []
    choice_votes = []
    if vote_id:
        current_vote = get_object_or_404(Vote, pk=vote_id)
    else:
        current_vote = Vote()
    if only_choices_after:
        choices_orig = current_poll.choice_set.filter(
            deleted=False, date__gt=only_choices_after
        ).order_by("sort_key")
    else:
        choices_orig = current_poll.choice_set.filter(deleted=False).order_by(
            "sort_key"
        )
    for choice in choices_orig:
        cur_comment = ""
        value = None
        if request.method == "POST":
            if str(choice.id) in request.POST:
                value = get_object_or_404(ChoiceValue, id=request.POST[str(choice.id)])
            else:
                value = None
            cur_comment = request.POST.get("comment_{}".format(choice.id)) or ""
        elif vote_id:  # If we want to edit an vote find the selected fields
            vote_choice = VoteChoice.objects.filter(vote=vote_id, choice=choice.id)
            if vote_choice:  # append the found values
                cur_comment = vote_choice[0].comment
                value = vote_choice[0].value
        choices.append(choice)
        comments.append(cur_comment)
        choice_votes.append(value)

    events = get_caldav(
        choices, current_poll, request.user, request
    )  # TODO check if we broke anything in CalDAV handling

    reduced_template = True if "reduced" in request.GET else False

    return TemplateResponse(
        request,
        "poll/vote_creation.html",
        {
            "basetemplate_name": "base.html"
            if not reduced_template
            else "base_reduced.html",
            "poll": current_poll,
            "matrix": matrix,
            "matrix_len": len(matrix[0]),
            "choices_matrix": zip(matrix, choices, comments, choice_votes, events),
            "choices": current_poll.choice_set.all(),
            "choices_matrix_len": len(choices),
            "values": current_poll.choicevalue_set.filter(deleted=False).order_by(
                "-weight", "title"
            ),
            "page": "Vote",
            "current_vote": current_vote,
            "timezone_warning": (
                request.user.is_authenticated
                and current_poll.type != "date"
                and current_poll.get_tz_name(request.user) != request.user.timezone
            ),
            "choice_values": ChoiceValue.objects.filter(poll=current_poll),
            "url_append": "" if not reduced_template else "?reduced",
        },
    )


def vote_assign(request, poll_url, vote_id):
    current_poll = get_object_or_404(Poll, url=poll_url)
    current_vote = get_object_or_404(Vote, id=vote_id)

    if request.method == "POST":
        if request.user.is_authenticated and current_vote.can_edit(request.user):
            username = request.POST.get("username").strip()
            try:
                user = BitpollUser.objects.get(username=username)
                if (
                    not current_poll.vote_set.filter(Q(user=user))
                    and current_poll.one_vote_per_user
                ):
                    current_vote.user = user
                    current_vote.name = user.get_displayname()
                    current_vote.assigned_by = request.user
                    current_vote.save()
                    return redirect("poll", poll_url)
                else:
                    messages.info(
                        request,
                        _(
                            "This user has already voted and only one vote per user is permitted"
                        ),
                    )
            except ObjectDoesNotExist:
                messages.warning(
                    request, _("The user {} does not exists".format(username))
                )
        else:
            return HttpResponseForbidden()

    return TemplateResponse(
        request, "poll/vote_assign.html", {"poll": current_poll, "vote": current_vote}
    )


def vote_delete(request, poll_url, vote_id):
    """
    :param request:
    :param poll_url: url of Poll belonging to vote
    :param vote_id: ID of vote to be deleted
    :return:

    Case Delete:
        If the user is authenticated and is equal to the saved user in the vote, the current vote is deleted.
        The user is redirected to the poll's page.

        If the user is authenticated but not equal to the saved user, the user is directed back with
        error message "Deletion not allowed. You are not [user of vote]".

        If the user is not authenticated, the user is directed back with error message
        "Deletion not allowed. You are not authenticated."

    Case Cancel:
        The user is directed back to the poll's page.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    current_vote = get_object_or_404(Vote, id=vote_id)
    reduced_template = True if "reduced" in request.GET else False
    error_msg = ""

    if request.method == "POST":
        if "Delete" in request.POST:
            if request.user.is_authenticated:
                # TODO additional possibilities of deleting
                if current_vote.can_delete(request.user):
                    current_vote.delete()
                    response = redirect("poll", poll_url)
                    if reduced_template:
                        response["Location"] += "?reduced"
                    return response
                else:
                    error_msg = _(
                        "Deletion not allowed. You are not {}.".format(
                            str(current_vote.name)
                        )
                    )
            else:
                error_msg = _("Deletion not allowed. You are not authenticated.")
        else:
            response = redirect("poll", poll_url)
            if reduced_template:
                response["Location"] += "?reduced"
            return response

    return TemplateResponse(
        request,
        "poll/vote_delete.html",
        {
            "basetemplate_name": "base.html"
            if not reduced_template
            else "base_reduced.html",
            "url_append": "?reduced" if reduced_template else "",
            "poll": current_poll,
            "vote": current_vote,
            "error": error_msg,
        },
    )


def copy(request, poll_url):
    """
    :param request:
    :param poll_url: Url of current poll
    :return:

    Takes a new title (optional), a new url (required) and a new due_date (required) as user input.
    Current poll is copied. Title, url and due-date are adapted.
    The new Poll is saved and the user is directed to its page.
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    date_shift = 0
    error_msg = ""
    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    if request.method == "POST":
        form = PollCopyForm(request.POST)

        if form.is_valid():
            copy_choices = form.data.get("copy_choices", "")
            copy_invitations = form.data.get("copy_invitations", "")
            create_invitations_from_votes = form.data.get(
                "create_invitations_from_votes", False
            )
            copy_answer_values = form.data.get("copy_ans_values", "")
            reset_ownership = form.data.get("reset_ownership", "")
            date_shift = int(form.data.get("date_shift", ""))

            choice_values = current_poll.choicevalue_set.all()
            choices = current_poll.choice_set.all()
            invitations = current_poll.invitation_set.all()
            vote_users = current_poll.vote_set.all().values("user")
            invitation_users = invitations.values("user")

            current_poll.pk = None
            current_poll.title = form.cleaned_data["title"]
            current_poll.url = form.cleaned_data["url"]
            current_poll.due_date = form.cleaned_data["due_date"]

            if date_shift:
                current_poll.due_date += timedelta(days=date_shift)

            if reset_ownership:
                current_poll.user = None
                current_poll.group = None

            current_poll.save()

            if copy_invitations:
                for invitation in invitations:
                    invitation.pk = None
                    invitation.poll = current_poll
                    invitation.date_created = now()
                    invitation.last_email = None
                    invitation.creator = request.user
                    invitation.save()
                    invitation.send(request)

            if create_invitations_from_votes:
                for user in vote_users:
                    if user not in invitation_users:
                        invitation = Invitation(
                            poll=current_poll,
                            user=user,
                            date_created=now(),
                            creator=request.user,
                        )
                        invitation.save()
                        invitation.send(request)

            if copy_choices:
                for choice in choices:
                    choice.pk = None
                    choice.poll = current_poll
                    if date_shift and choice.date:
                        choice.date += timedelta(days=date_shift)
                    choice.save()

            if copy_answer_values:
                for value in choice_values:
                    value.pk = None
                    value.poll = current_poll
                    value.save()

            return redirect("poll", current_poll.url)

    else:
        form = PollCopyForm(
            {
                "title": "Copy of " + current_poll.title,
                "due_date": current_poll.due_date,
                "url": current_poll.url + "2",
            }
        )  # we set an url, this will be overwritten by the slug generation JS

    return TemplateResponse(
        request,
        "poll/copy.html",
        {
            "form": form,
            "poll": current_poll,
            "date_shift": date_shift,
            "error": error_msg,
        },
    )


def settings(request, poll_url):
    """

    :param request:
    :param poll_url:
    :return:
    """
    current_poll = get_object_or_404(Poll, url=poll_url)
    groups = None

    if request.user.is_authenticated:
        groups = Group.objects.filter(user=request.user)

    if not current_poll.can_edit(request.user, request):
        return redirect("poll", poll_url)

    user_error = ""
    user = current_poll.user.username if current_poll.user else ""
    if request.method == "POST":
        old_timezone_name = current_poll.timezone_name
        form = PollSettingsForm(request.POST, instance=current_poll)
        if form.is_valid():
            new_poll = form.save(commit=False)
            user = form.data.get("user", "")
            with transaction.atomic():
                if user:
                    try:
                        user_obj = BitpollUser.objects.get(username=user)
                        new_poll.user = user_obj
                    except ObjectDoesNotExist:
                        user_error = _("User {} not Found".format(user))
                else:
                    new_poll.user = None
                    current_poll.choice_set.all()
                if not user_error:
                    # change the Timezone in the Choices, date-polls are in UTC regardles of the timezone
                    if (
                        old_timezone_name != new_poll.timezone_name
                        and current_poll.type == "datetime"
                    ):
                        new_timezone = timezone(new_poll.timezone_name)
                        old_timezone = timezone(old_timezone_name)
                        for choice in current_poll.choice_set.all():
                            choice.date = make_aware(
                                make_naive(choice.date, old_timezone), new_timezone
                            )
                            choice.save()
                    new_poll.save()
                    messages.success(request, _("Settings have been changed"))
                    return redirect("poll_settings", current_poll.url)
        else:
            user = form.cleaned_data.get("user", "")
    else:
        form = PollSettingsForm(instance=current_poll)

    # we activate the base timezone of this poll so the due date etc is showed in the correct way.
    tz_activate(current_poll.timezone_name)

    return TemplateResponse(
        request,
        "poll/settings.html",
        {
            "form": form,
            "poll": current_poll,
            "page": "Settings",
            "groups": groups,
            "results": POLL_RESULTS,
            "timezones": all_timezones,
            "user_error": user_error,
            "user_select": user,
        },
    )


def transpose(matrix):
    return [list(i) for i in zip(*matrix)]
