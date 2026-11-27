# Renders for checking the model. The user's camera is always copied first and restored afterwards
# (view.camera is the LIVE camera object; the user works in the same window).
# Temporary section planes are made inside an operation that is aborted, so nothing stays in the model.
#   Shots.perspective('name', [ex,ey,ez], [tx,ty,tz], fov = 75)        -> views/<name>.png
#   Shots.plan('name', x0, x1, y0, y1, zcut, px = 2400)                  -> views/plan/<name>.png
#   Shots.section('name', [x,y], [nx,ny], [u0,u1], [z0,z1], px = 1600)   -> views/plan/<name>.png
#   Shots.from_json('cams.json')  {"key": {"name": [[eye], [target]]}}   -> views/<key>/<name>.png
# All coordinates in metres.
require 'json'
require 'fileutils'

module Shots
  ROOT = defined?(SuBridge) ? SuBridge::ROOT : File.expand_path('../..', File.dirname(__FILE__))

  def self.save_camera(v)
    c = v.camera
    s = Sketchup::Camera.new(c.eye, c.target, c.up, c.perspective?, c.fov)
    s.height = c.height unless c.perspective?
    s
  end

  def self.dir(*parts)
    d = File.join(ROOT, 'views', *parts)
    FileUtils.mkdir_p(d)
    d
  end

  def self.pt(a) Geom::Point3d.new(a[0].to_f.m, a[1].to_f.m, a[2].to_f.m) end

  def self.perspective(name, eye, target, fov = 75, w = 1400, h = 900, sub = nil)
    v = Sketchup.active_model.active_view
    saved = save_camera(v)
    begin
      v.camera = Sketchup::Camera.new(pt(eye), pt(target), Z_AXIS, true, fov)
      fn = File.join(sub ? dir(sub) : dir, "#{name}.png")
      v.write_image(filename: fn, width: w, height: h, antialias: true)
      fn
    ensure
      v.camera = saved
    end
  end

  def self.from_json(file)
    cams = JSON.parse(File.read(File.expand_path(file, ROOT)))
    out = []
    cams.each { |key, h| h.each { |name, (e, t)| out << perspective(name, e, t, 75, 1400, 900, key) } }
    out.join("\n")
  end

  def self.plan(name, x0, x1, y0, y1, zcut, px = 2400)
    m = Sketchup.active_model; v = m.active_view
    saved = save_camera(v)
    m.start_operation('plan shot', true)
    begin
      sp = m.entities.add_section_plane([Geom::Point3d.new(0, 0, zcut.m), Geom::Vector3d.new(0, 0, -1)])
      sp.activate
      cx = (x0 + x1) / 2.0; cy = (y0 + y1) / 2.0
      cam = Sketchup::Camera.new(Geom::Point3d.new(cx.m, cy.m, (zcut + 50).m), Geom::Point3d.new(cx.m, cy.m, 0), Y_AXIS, false)
      w = x1 - x0; h = y1 - y0
      cam.height = h.m
      v.camera = cam
      fn = File.join(dir('plan'), "#{name}.png")
      v.write_image(filename: fn, width: px, height: (px * h / w).round, antialias: true)
      fn
    ensure
      m.abort_operation
      v.camera = saved
    end
  end

  def self.section(name, p, n, ur, zr, px = 1600)
    m = Sketchup.active_model; v = m.active_view
    saved = save_camera(v)
    m.start_operation('section shot', true)
    begin
      nn = Geom::Vector3d.new(n[0], n[1], 0).normalize
      sp = m.entities.add_section_plane([Geom::Point3d.new(p[0].m, p[1].m, 0), nn.reverse])
      sp.activate
      d = Geom::Vector3d.new(-nn.y, nn.x, 0)
      uc = (ur[0] + ur[1]) / 2.0; zc = (zr[0] + zr[1]) / 2.0
      tgt = Geom::Point3d.new(p[0].m + d.x * uc.m, p[1].m + d.y * uc.m, zc.m)
      cam = Sketchup::Camera.new(tgt.offset(nn.reverse, 60.m), tgt, Z_AXIS, false)
      cam.height = [zr[1] - zr[0], (ur[1] - ur[0]) * 0.5625].max.m
      v.camera = cam
      fn = File.join(dir('plan'), "#{name}.png")
      v.write_image(filename: fn, width: px, height: (px * 0.5625).round, antialias: true)
      fn
    ensure
      m.abort_operation
      v.camera = saved
    end
  end
end
