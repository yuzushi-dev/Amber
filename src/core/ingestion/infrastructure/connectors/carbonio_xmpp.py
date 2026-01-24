"""
Carbonio WebSocket XMPP Client
==============================

Custom XMPP client using WebSocket transport (RFC 7395) for Carbonio chat history.
"""

import logging
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

logger = logging.getLogger(__name__)

# XMPP namespaces
NS_FRAMING = "urn:ietf:params:xml:ns:xmpp-framing"
NS_JABBER_CLIENT = "jabber:client"
NS_SASL = "urn:ietf:params:xml:ns:xmpp-sasl"
NS_MAM = "urn:xmpp:mam:2"
NS_RSM = "http://jabber.org/protocol/rsm"
NS_FORWARD = "urn:xmpp:forward:0"
NS_DELAY = "urn:xmpp:delay"


class CarbonioWebSocketXMPP:
    """
    WebSocket XMPP client for Carbonio using RFC 7395 framing.
    """
    
    def __init__(self, host: str, auth_token: str, email: str = "", cookies: Optional[Dict[str, str]] = None, xmpp_uuid: str = None):
        """
        Initialize the WebSocket XMPP client.
        
        Args:
            host: Carbonio server host
            auth_token: ZM_AUTH_TOKEN
            email: User's email address
            cookies: Optional dict of cookies
            xmpp_uuid: Optional explicit UUID for SASL auth
        """
        self.host = host.rstrip("/")
        self.auth_token = auth_token
        self.email = email
        self.cookies = cookies or {}
        self.xmpp_uuid = xmpp_uuid
        
        # Ensure auth token is in cookies
        if "ZM_AUTH_TOKEN" not in self.cookies and auth_token:
            self.cookies["ZM_AUTH_TOKEN"] = auth_token
            
        self.xmpp_token: Optional[str] = None
        self.ws = None
        self._connected = False
        self._stream_id = None
        
    def _get_domain(self) -> str:
        """Extract domain from host URL."""
        import urllib.parse
        parsed = urllib.parse.urlparse(self.host)
        return parsed.netloc or parsed.path
    
    def _get_jid(self) -> str:
        """Get full JID from email."""
        if self.email:
            local = self.email.split("@")[0]
            return f"{local}@{self._get_domain()}"
        return f"user@{self._get_domain()}"
        
    async def get_xmpp_token(self) -> Optional[str]:
        """Get XMPP token and session cookies."""
        try:
            # Prepare initial cookies
            cookies = self.cookies.copy()
            domain = self._get_domain()
            
            async with httpx.AsyncClient(
                verify=False, 
                timeout=30.0,
                cookies=cookies,
                follow_redirects=True
            ) as client:
                # 1. Hit the web UI to try and get JSESSIONID (optional)
                # logger.info(f"Warming up session at https://{domain}/carbonio/")
                # await client.get(f"https://{domain}/carbonio/")
                # self.cookies.update(client.cookies)
                
                # 2. Get XMPP token
                resp = await client.get(f"{self.host}/services/chats/auth/token")
                
                if resp.status_code == 200:
                    data = resp.json()
                    self.xmpp_token = data.get("zmToken") or data.get("token")
                    token_uuid = data.get("id") or data.get("username")
                    if token_uuid and not self.xmpp_uuid:
                        self.xmpp_uuid = token_uuid
                    
                    # Merge response cookies
                    self.cookies.update(resp.cookies)
                    
                    logger.info(f"Got XMPP token: {self.xmpp_token[:30] if self.xmpp_token else 'None'}...")
                    logger.info(f"Got XMPP UUID: {self.xmpp_uuid}")
                    logger.info(f"Cookies for WS: {list(self.cookies.keys())}")
                    return self.xmpp_token
                else:
                    logger.error(f"Failed to get XMPP token: {resp.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Exception getting XMPP token: {e}")
            return None

    async def connect(self) -> bool:
        """
        Establish WebSocket connection and perform XMPP handshake.
        """
        try:
            import websockets
            
            # Get XMPP token first (this will populate self.cookies)
            if not self.xmpp_token:
                await self.get_xmpp_token()
                
            if not self.xmpp_token:
                logger.error("Cannot connect: No XMPP token")
                return False
            
            domain = self._get_domain()
            
            # Use the correct endpoint for XMPP
            ws_url = f"wss://{domain}/services/messaging/ws-xmpp"
            
            logger.info(f"Connecting to WebSocket: {ws_url}")
            
            # Prepare cookie string for headers
            cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])

            # Connect via WebSocket with XMPP subprotocol
            # Include Origin header to match browser behavior
            # Do NOT send Host header manually, let websockets handle it
            self.ws = await websockets.connect(
                ws_url,
                subprotocols=["xmpp"],
                additional_headers={
                    "Cookie": cookie_header,
                    "Origin": f"https://{domain}",
                },
                ssl=True
            )
            
            logger.info("WebSocket connected, sending XMPP open")
            
            # Send RFC 7395 open element
            # Browser sends to="carbonio", not the domain name
            open_stanza = f'''<open xmlns="{NS_FRAMING}" to="carbonio" version="1.0"/>'''
            await self.ws.send(open_stanza)
            
            # Wait for stream features (handle case where open and features are separate)
            has_features = False
            for _ in range(5): # retry loop
                try:
                    response = await asyncio.wait_for(self.ws.recv(), timeout=5)
                    logger.info(f"Handshake response: {response[:200]}...")
                    if "stream:features" in response or "features" in response.lower():
                        has_features = True
                        break
                except asyncio.TimeoutError:
                    break
            
            # Parse features and handle SASL auth
            if has_features:
                # Need to authenticate
                auth_success = await self._authenticate()
                if not auth_success:
                    logger.error("XMPP authentication failed")
                    return False
            else:
                logger.warning("No stream features received, proceeding without auth (likely to fail)")
            
            self._connected = True
            logger.info("XMPP WebSocket connection established")
            return True
            
        except ImportError:
            logger.error("websockets library not installed")
            return False
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def _authenticate(self) -> bool:
        """Perform SASL PLAIN authentication with zmToken."""
        try:
            import base64
            
            # Use UUID if available, otherwise JID (fallback)
            username = self.xmpp_uuid if self.xmpp_uuid else self._get_jid()
            
            # SASL PLAIN: \0username\0password (where username is UUID)
            auth_string = f"\x00{username}\x00{self.xmpp_token}"
            auth_b64 = base64.b64encode(auth_string.encode()).decode()
            
            # Send SASL auth
            auth_stanza = f'<auth xmlns="{NS_SASL}" mechanism="PLAIN">{auth_b64}</auth>'
            await self.ws.send(auth_stanza)
            
            # Wait for success or failure
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            logger.info(f"Auth response: {response[:200]}...")
            
            if "success" in response.lower():
                logger.info("SASL authentication successful")
                
                # Restart stream after auth (RFC 7395)
                # Browser sends to="carbonio" here too
                await self.ws.send(f'<open xmlns="{NS_FRAMING}" to="carbonio" version="1.0"/>')
                
                # Get new stream features (handle split frames again)
                for _ in range(5):
                    try:
                        response = await asyncio.wait_for(self.ws.recv(), timeout=5)
                        logger.info(f"Post-auth response: {response[:200]}...")
                        if "bind" in response.lower() or "stream:features" in response:
                            break
                    except asyncio.TimeoutError:
                        break
                
                # Perform Resource Binding (Required)
                bind_iq = f'<iq type="set" id="bind_1"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind"/></iq>'
                await self.ws.send(bind_iq)
                
                # Wait for Bind Result
                try:
                    bind_response = await asyncio.wait_for(self.ws.recv(), timeout=10)
                    logger.info(f"Bind response: {bind_response[:200]}...")
                    if 'type="result"' in bind_response and "bind" in bind_response:
                        logger.info("XMPP Resource Binding successful")
                    elif 'type="error"' in bind_response:
                        logger.error(f"XMPP Resource Binding failed: {bind_response}")
                        return False
                except asyncio.TimeoutError:
                    logger.error("Timeout waiting for resource binding")
                    return False

                # Establish Session (if offered, usually yes for legacy/ejabberd)
                session_iq = f'<iq type="set" id="session_1"><session xmlns="urn:ietf:params:xml:ns:xmpp-session"/></iq>'
                await self.ws.send(session_iq)
                
                try:
                    session_response = await asyncio.wait_for(self.ws.recv(), timeout=5)
                    logger.info(f"Session response: {session_response[:200]}...")
                except asyncio.TimeoutError:
                    # Session establishment might be silent or optional, but usually returns result
                    logger.warning("Timeout waiting for session establishment (proceeding)")

                return True
            else:
                logger.error(f"SASL auth failed: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    async def get_room_history(
        self, 
        room_id: str, 
        limit: int = 50,
        search_query: str = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch message history for a room using XEP-0313 MAM.
        
        Args:
            room_id: The room UUID
            limit: Max messages to fetch (default 50)
            search_query: Optional string to filter messages by
        """
        if not self._connected or not self.ws:
            # Try to connect first
            if not await self.connect():
                logger.error("Not connected to XMPP")
                return []
        
        try:
            # Use carbonio domain for MUC Light as observed in browser
            room_jid = f"{room_id}@muclight.carbonio"
            
            # If searching, increase limit to scan more history (unless limit is already high)
            if search_query and limit < 300:
                limit = 300
            
            # Send Ping to verify connection
            ping_id = f"ping_{int(datetime.now().timestamp())}"
            ping_stanza = f"<iq type='get' to='carbonio' id='{ping_id}'><ping xmlns='urn:xmpp:ping'/></iq>"
            logger.info(f"Sending Ping: {ping_stanza}")
            await self.ws.send(ping_stanza)
            
            # Wait for Ping Result
            try:
                ping_response = await asyncio.wait_for(self.ws.recv(), timeout=5)
                logger.debug(f"Ping response: {ping_response[:200]}")
            except asyncio.TimeoutError:
                logger.warning("Ping timeout")
            
            # Build MAM query IQ with x-data form as observed in browser behavior
            query_id = f"mam_{int(datetime.now().timestamp())}"
            mam_query = f'''<iq type="set" to="{room_jid}" id="{query_id}">
                <query xmlns="{NS_MAM}" queryid="13">
                    <x xmlns="jabber:x:data" type="submit">
                        <field type="hidden" var="FORM_TYPE">
                            <value>{NS_MAM}</value>
                        </field>
                    </x>
                    <set xmlns="{NS_RSM}">
                        <max>{limit}</max>
                        <before/>
                    </set>
                </query>
            </iq>'''
            
            logger.info(f"Sending MAM query to {room_jid} (limit={limit})")
            await self.ws.send(mam_query)
            
            messages = []
            
            # Collect messages until we get the IQ result
            while True:
                try:
                    response = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    logger.info(f"DEBUG: Received: {response[:500]}...")
                    
                    # Check for MAM result messages
                    # Handle both single and double quotes in xmlns
                    if NS_MAM in response and 'result' in response:
                        try:
                            # Use simple string extraction for robustness if XML parsing fails due to fragments
                            # or just use element tree on the stanza
                            
                            sender = None
                            body_text = None
                            timestamp = None
                            
                            import re
                            
                            # Log the first response fully to debug structure
                            if not hasattr(self, "_logged_debug_xml"):
                                logger.info(f"DEBUG: FIRST XML RESPONSE: {response}")
                                self._logged_debug_xml = True

                            # Robust regex extraction for body and delay
                            # Matches <body ...> or <g2:body ...> or <client:body ...>
                            body_match = re.search(r"<([a-zA-Z0-9_:]*body)[^>]*>(.*?)</\1>", response, re.DOTALL | re.IGNORECASE)
                            if body_match:
                                body_text = body_match.group(2)
                                
                                # Extract timestamp
                                timestamp = ""
                                ts_match = re.search(r'stamp=[\'"]([^\'"]+)[\'"]', response)
                                if ts_match:
                                    timestamp = ts_match.group(1)
                                
                                # Extract sender (from attribute)
                                sender_full = ""
                                sender_match = re.search(r'from=[\'"]([^\'"]+)[\'"]', response)
                                if sender_match:
                                    sender_full = sender_match.group(1)
                                    # Extract resource if present (e.g., user@domain/resource)
                                    if '/' in sender_full:
                                        sender = sender_full.split('/')[-1]
                                    else:
                                        sender = sender_full.split('@')[0] # Fallback to username part
                                
                                # Since we want robust extraction, let's look for known fields
                                messages.append({
                                    "content": body_text,
                                    "timestamp": timestamp,
                                    "sender": sender if sender else "Participant" # Placeholder if parsing fails
                                })
                        except Exception as e:
                            logger.error(f"Error parsing message XML: {e}")
                    
                    # Check for query completion (IQ result)
                    if f'id="{query_id}"' in response:
                        logger.info("MAM query complete")
                        break
                        
                except asyncio.TimeoutError:
                    logger.warning("MAM response timeout")
                    break
            
            logger.info(f"Retrieved {len(messages)} messages total")
            
            # Filter if search query provided
            if search_query:
                query_lower = search_query.lower()
                
                # Try to parse as date (multiple formats)
                parsed_date = None
                import re
                from dateutil import parser as dateparser
                
                # Common patterns: "January 9", "Jan 9, 2026", "2026-01-09", "9 January"
                try:
                    # Use dateutil for flexible parsing
                    parsed_date = dateparser.parse(search_query, fuzzy=True)
                    if parsed_date:
                        logger.info(f"Parsed date from query: {parsed_date.date()}")
                except:
                    pass
                
                filtered = []
                for m in messages:
                    content_match = query_lower in m["content"].lower()
                    
                    # Also check timestamp match if we parsed a date
                    timestamp_match = False
                    if parsed_date and m.get("timestamp"):
                        try:
                            msg_ts = dateparser.parse(m["timestamp"])
                            if msg_ts and msg_ts.date() == parsed_date.date():
                                timestamp_match = True
                        except:
                            pass
                    
                    if content_match or timestamp_match:
                        filtered.append(m)
                
                logger.info(f"Filtered to {len(filtered)} messages matching '{search_query}' (content or date)")
                return filtered
                
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get room history: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def close(self):
        """Close XMPP session and WebSocket."""
        if self.ws and self._connected:
            try:
                await self.ws.send(f'<close xmlns="{NS_FRAMING}"/>')
                await self.ws.close()
            except:
                pass
            self._connected = False
            logger.info("WebSocket XMPP disconnected")


async def get_chat_history(
    host: str,
    auth_token: str,
    room_id: str,
    email: str = "",
    cookies: Optional[Dict[str, str]] = None,
    limit: int = 50,
    xmpp_uuid: str = None,
    search_query: str = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to get chat history via WebSocket XMPP.
    """
    client = CarbonioWebSocketXMPP(host, auth_token, email, cookies, xmpp_uuid)
    
    try:
        messages = await client.get_room_history(room_id, limit, search_query)
        return messages
    finally:
        await client.close()
