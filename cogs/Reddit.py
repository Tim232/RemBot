from config import reddit
import asyncpraw
from discord.ext import commands, flags
import discord
import json
import asyncio
import sys
import traceback
import datetime
from urllib.parse import urlparse

praw = asyncpraw.Reddit(client_id=reddit['id'], client_secret=reddit['secret'], user_agent="RemBot by /u/IBOSSWOLF")


# TODO: Add ability to handle more than one feed at once
class FeedHandler:
    def __init__(self, bot, sub, limit, current, ctx):
        self.bot = bot
        self.ctx = ctx
        self.channel_id = ctx.channel.id
        self.sub = None
        self.icon = None
        self.upvote_limit = limit
        self.currently_checking = {}  # type: dict[str, asyncio.Task]
        self.timer = self.loop.create_task(self.auto_handler_task(sub))
        self.webhook = discord.Webhook.from_url(await self.check_webhook(sub),
                                                adapter=discord.AsyncWebhookAdapter(bot.session))

        for sub in current:
            if self.upvote_limit == 0:  # 0 = don't bother checking
                self.loop.create_task(self.dispatch(sub))
            else:
                self.currently_checking[sub] = self.loop.create_task(self.check(sub))

    def __repr__(self):
        return (f"FeedHandler({self.channel_id}, {self.sub}, {self.upvote_limit}, {self.currently_checking}, "
                f"{self.webhook.url})")

    async def auto_handler_task(self, sub):
        self.sub = await praw.subreddit(sub)
        await self.sub.load()
        await self.bot.wait_until_ready()
        try:
            async for submission in self.sub.stream.submissions(skip_existing=True):
                print(f"Received submission: /r/{sub}/comments/{submission}")
                sub = submission.id
                if self.upvote_limit == 0:
                    await self.dispatch(sub)
                else:
                    self.currently_checking[sub] = self.loop.create_task(self.check(sub))
                await asyncio.sleep(10)
        except Exception as e:
            print("Error occurred during automatic handler:", file=sys.stderr)
            traceback.print_exception(type(e), e, e.__traceback__)

    async def check(self, sub):
        await self.bot.wait_until_ready()
        tries = 12
        try:
            while tries:
                sub = await praw.submission(id=sub)
                await sub.load()
                print(f"Checking if /r/{self.sub.display_name}/comments/{sub} has reached upvote threshold "
                      f"({sub.score}/{self.upvote_limit}) ({12 - tries} attempts remaining)")
                if sub.score >= self.upvote_limit:
                    await self.dispatch(sub)
                    break
                tries -= 1
                await asyncio.sleep(360)
        except Exception as e:
            print("Error occurred during periodic updater:")
            traceback.print_exception(type(e), e, e.__traceback__)
        finally:
            task = self.currently_checking.pop(sub, None)
            if task:
                task.cancel()

    async def check_webhook(self, sub):
        # Maya I'm so sorry
        webhook = discord.utils.get(await self.ctx.channel.webhooks(), name=f"/r/{sub}")

        if webhook is None:
            webhook = await self.ctx.channel.create_webhook(name=f"/r/{sub}",
                                                            avatar=self.icon[self.sub.display_name])

        return webhook

    def get_community_icon(self):
        o = urlparse(self.sub.community_icon)
        return f"{o.scheme}://{o.netloc}{o.path}"

    async def dispatch(self, sub):
        print(f"Dispatching /r/{self.sub.display_name}/comments/{sub}")
        submit = await praw.submission(id=sub)
        embed = discord.Embed(colour=discord.Colour.blue(), title=submit.title,
                              url=f"https://reddit.com{submit.permalink}",
                              timestamp=datetime.datetime.utcfromtimestamp(int(submit.created_utc)))
        self.icon = self.sub.icon_img or self.get_community_icon()
        embed.set_author(icon_url=self.icon,
                         url=f"https://reddit.com/r/{self.sub.display_name}",
                         name=f"/r/{self.sub.display_name}")
        embed.set_footer(text=f"/u/{submit.author.name}")
        if submit.url.endswith((".jpg", ".png", ".jpeg", ".webp", ".webm", ".gif", ".gifv")):
            embed.set_image(url=submit.url)
        if submit.selftext:
            embed.description = submit.selftext[:2040] + "..."
        try:
            await self.webhook.send(embed=embed)
        except discord.NotFound:  # webhook was deleted
            if self.channel is None:  # channel was deleted
                self.timer.cancel()
                return
            try:
                self.webhook = {
                    webhook.name: webhook
                    for webhook in await self.channel.webhooks()
                }.get(f"/r/{sub}", await self.channel.create_webhook(name=f"/r/{sub}"))
                await self.dispatch(sub)
            except discord.Forbidden:  # no perms to make a new webhook
                self.timer.cancel()
                return
        except Exception as e:
            print("Error occurred whilst dispatching", file=sys.stderr)
            traceback.print_exception(type(e), e, e.__traceback__)

    @property
    def loop(self):
        return self.bot.loop

    @property
    def channel(self):
        return self.bot.get_channel(self.channel_id)

    def to_json(self):
        return {"sub": self.sub, "limit": self.upvote_limit,
                "current": [sub for sub in self.currently_checking],
                "webhook": self.webhook.url}


class Reddit(commands.Cog):
    """Base cog for auto-reddit feed related commands."""

    def __init__(self, bot):
        self.bot = bot
        self.feeds = {}  # type: dict[int, list[FeedHandler]]
        bot.loop.run_until_complete(self.prepare_auto_feeds())

    async def prepare_auto_feeds(self):
        # TODO: use a database
        with open("feeds.json") as f:
            feeds = json.load(f)
        for i, data in feeds.items():
            self.feeds[int(i)].append(FeedHandler(self.bot, int(i), **data))

    # TODO: Don't forget to implement --image-only
    @flags.add_flag("-u", "--upvote-limit", type=int,
                    help="The required amount of upvotes before dispatching.", default=0)
    @reddit.command(cls=flags.FlagCommand)
    @commands.has_permissions(manage_channels=True, manage_webhooks=True)
    @commands.bot_has_permissions(manage_webhooks=True)
    async def new(self, ctx, sub, **options):
        """Creates a new reddit feed."""
        async with self.bot.session.get(f"https://reddit.com/r/{sub}.json") as f:
            if f.status != 200:
                await ctx.send("Unknown subreddit! :c")
                return

        feed = FeedHandler(self.bot, sub, limit=options['upvote_limit'], current=[], ctx=ctx)

        if feed in [feed for feed in self.feeds[ctx.channel.id]]:
            await ctx.send("This subreddit is already being fed here!")
            return

        self.feeds[ctx.channel.id].append(feed)

        # TODO: Show flags and their settings if commands were invoked with flags
        await ctx.send("Done! You should now get express images straight from Reddit!~")


def setup(bot):
    bot.add_cog(Reddit(bot))
