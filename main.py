import discord
from discord.ext import commands
import glob
import config
import os
import sys
import traceback

bot = commands.Bot(
	commands.when_mentioned, 
	intents=discord.Intents.all(),
	owner_ids={155159390637260800, 455289384187592704},
	activity=discord.Game("with your feelings 💙 | @ me for help!")
)

try:
	bot.load_extension('jishaku')
	print("Found and loaded Jishaku")
except commands.ExtensionError:
	pass

for file in glob.glob("cogs/*.py"):
	fname = file.replace(os.sep, '.')[:-3]
	try:
		bot.load_extension(fname)
		print("Found and loaded", fname)
	except commands.ExtensionError as e:
		print("Failed to load", fname, file=sys.stderr)
		traceback.print_exc()

@bot.event
async def on_ready():
	print("Ready!", bot.user.name, bot.user.id)

@bot.command()
@commands.is_owner()
async def reload(ctx, ext=None):
	if ext is not None:
		try:
			bot.reload_extension('cogs.'+ext)
		except:
			await ctx.send(f"An error occured while reloading {ext}\n```py\n{traceback.format_exc()}\n```")
	else:
		for file in glob.glob("cogs/*.py"):
			fname = file.replace(os.sep, '.')[:-3]
			try:
				bot.reload_extension(fname)
				await ctx.send(f"Found and reloaded {fname}")
			except:
				await ctx.send(f"An error occured while reloading {fname}\n```py\n{traceback.format_exc()}\n```")
		
bot.run(config.token)
