# Bridge so Claude can run its own Ruby scripts in THIS SketchUp window.
# Load once per SketchUp session in Extensions > Developer > Ruby Console:
#   load 'C:/Users/Nino/Drawing assistant/tools/sketchup/su_bridge.rb'
# Every second it checks <repo>/bridge/inbox. Each *.rb file found there is run in this window,
# the result is written to <repo>/bridge/outbox/<name>.out ("OK\n<result>" or "ERROR ...\n<backtrace>"),
# and the input file is deleted. Stop it any time with:  SuBridge.stop
# The agent side is tools/sketchup/su_query.ps1.
require 'fileutils'

module SuBridge
  ROOT = File.expand_path('../..', File.dirname(__FILE__))
  INBOX = File.join(ROOT, 'bridge', 'inbox')
  OUTBOX = File.join(ROOT, 'bridge', 'outbox')
  TOOLS = File.join(ROOT, 'tools', 'sketchup')

  def self.start
    FileUtils.mkdir_p(INBOX)
    FileUtils.mkdir_p(OUTBOX)
    stop
    @busy = false
    @timer = UI.start_timer(1.0, true) { tick }
    File.write(File.join(OUTBOX, '_bridge_started.out'),
               "started #{Time.now} sketchup=#{Sketchup.version} model=#{Sketchup.active_model.title}")
    puts "SuBridge running: #{INBOX}"
  end

  def self.stop
    UI.stop_timer(@timer) if @timer
    @timer = nil
  end

  def self.running?
    !@timer.nil?
  end

  # Helper for queries: load a tool from tools/sketchup by file name.
  def self.use(name)
    load File.join(TOOLS, name.end_with?('.rb') ? name : "#{name}.rb")
  end

  def self.tick
    return if @busy
    files = Dir.glob(File.join(INBOX, '*.rb')).sort
    return if files.empty?
    @busy = true
    files.each do |f|
      name = File.basename(f, '.rb')
      code = File.read(f, encoding: 'UTF-8')
      File.delete(f)
      out = begin
        res = eval(code, TOPLEVEL_BINDING, f)
        "OK\n#{res.is_a?(String) ? res : res.inspect}"
      rescue Exception => e
        "ERROR #{e.class}: #{e.message}\n#{(e.backtrace || []).first(8).join("\n")}"
      end
      File.write(File.join(OUTBOX, "#{name}.out"), out, encoding: 'UTF-8')
    end
  ensure
    @busy = false
  end
end

SuBridge.start
